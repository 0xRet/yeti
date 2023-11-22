import json
import logging
import re

import requests
from core import taskmanager
from core.config.config import yeti_config
from core.schemas import observable, task
from core.schemas.observable import Observable, ObservableType


class DockerHubAPI(object):
    """Base class for querying the DockerHub API."""

    @staticmethod
    def _make_request(endpoint) -> dict:
        response = requests.get(endpoint, allow_redirects=True)
        if response:
            return response.json()
        return {}

    @staticmethod
    def _iter_endpoint_pages(endpoint) -> dict:
        data = DockerHubAPI._make_request(endpoint)
        while data:
            for result in data.get("results", []):
                yield result
            next = data.get("next")
            if next:
                data = DockerHubAPI._make_request(next)
            else:
                data = {}

    @staticmethod
    def inspect_image(image, tag=None) -> dict:
        if tag:
            endpoint = (
                f"https://hub.docker.com/v2/repositories/{image}/tags/{tag}/images"
            )
        else:
            endpoint = f"https://hub.docker.com/v2/repositories/{image}"
        return DockerHubAPI._make_request(endpoint)

    @staticmethod
    def inspect_user(user) -> dict:
        endpoint = f"https://hub.docker.com/v2/orgs/{user}"
        # if orgs does not exist, redirects to
        # https://hub.docker.com/v2/users/
        return DockerHubAPI._make_request(endpoint)

    @staticmethod
    def user_images(user, page_size=50) -> iter:
        endpoint = f"https://hub.docker.com/v2/repositories/{user}?page_size={page_size}&ordering=last_updated"
        yield from DockerHubAPI._iter_endpoint_pages(endpoint)

    # https://hub.docker.com/v2/repositories/yetiplatform/yeti/tags/2.0.1

    @staticmethod
    def image_tags(image, page_size=100) -> iter:
        endpoint = f"https://hub.docker.com/v2/repositories/{image}/tags/?page_size={page_size}&page=1&name&ordering"
        yield from DockerHubAPI._iter_endpoint_pages(endpoint)

    def image_full_details(image):
        if image.find("/") == -1:
            return {}
        if image.find(":") != -1:
            image, tag = image.split(":")
        else:
            tag = ""
        image_metadata = DockerHubAPI.inspect_image(image)
        if not image_metadata:
            return {}
        image_metadata["user"] = DockerHubAPI.inspect_user(image_metadata.get("user"))
        image_metadata["tags"] = dict()
        if tag:
            image_metadata["tags"][tag] = DockerHubAPI.inspect_image(image, tag)
        else:
            for tag in DockerHubAPI.image_tags(image):
                tag_name = tag.get("name")
                image_metadata["tags"][tag_name] = DockerHubAPI.inspect_image(
                    image, tag_name
                )
        return image_metadata


class DockerImageInspect(task.OneShotTask):
    """DockerImageInspect analytics queries docker hub to get more
    details related to docker_image observable.

    This analytics adds several information as context to docker_image:
    * Image stats: provide details about pulls, registered, updated
    * Image details: provide information related to image tags including layers information and instructions
    * User details: provides details about the user owning the image.

    This analytics also creates new observables:
    * generic observable with tag type:user_account to link to a user
    * sha256 including image's digest, layers' digests and added files' digests
    """

    _defaults = {
        "name": "DockerImageMetadata",
        "description": "Fetch metadata from docker hub for a docker image",
    }

    acts_on: list[ObservableType] = [
        ObservableType.docker_image,
    ]

    def _get_observable(self, obs_type, value):
        cls = observable.TYPE_MAPPING[obs_type]
        obs = cls.find(value=value)
        if not obs:
            obs = cls(value=value).save()
        return obs

    def _get_context(self, metadata):
        context = {"source": "hub.docker.com"}
        if metadata:
            context["Analysis"] = "Image found"
            context["Image stats"] = {
                "Pulls": metadata.get("pull_count", "N/A"),
                "Last updated": metadata.get("last_updated", "N/A"),
                "Registered": metadata.get("date_registered", "N/A"),
                "Stars": metadata.get("star_count", "N/A"),
            }
            context["Image details"] = metadata.get("tags", "N/A")
            context["User details"] = metadata.get("user", "Unknown")
        else:
            context["Analysis"] = "Image not found"
        return context

    def _create_digest_context(self, image_obs, tag_name, image_tag):
        if not image_tag:
            return {}
        fullname = f"{image_obs.value}:{tag_name}"
        arch = image_tag.get("arch", "N/A")
        os = image_tag.get("os", "N/A")
        pushed = image_tag.get("last_pushed", "N/A")
        context = {"image name": fullname, "arch": f"{os}/{arch}", "pushed": pushed}
        return context

    def _create_digest_observable(self, image_obs, digest, context, link_type):
        sha_obs = self._get_observable(observable.ObservableType.sha256, value=digest)
        if context:
            sha_obs.add_context("hub.docker.com", context)
            sha_obs.tag({"dockerhub"})
        image_obs.link_to(sha_obs, link_type, "")
        return sha_obs

    def _make_relationships(self, image_obs, metadata):
        username = metadata.get("user", {}).get("username", "")
        if username:
            user_obs = self._get_observable(
                observable.ObservableType.generic, value=username
            )
            user_obs.tag({"type:user_account", "dockerhub"})
            user_obs.link_to(image_obs, "creates", "")
        for tag_name, image_tags in metadata.get("tags", {}).items():
            for image_tag in image_tags:
                context = self._create_digest_context(image_obs, tag_name, image_tag)
                digest = re.match(
                    r"sha256:([0-9a-f]{64})$",
                    image_tag.get("digest", ""),
                    re.IGNORECASE,
                )
                if digest:
                    self._create_digest_observable(
                        image_obs, digest.group(1), context, "results_to"
                    )
                for layer in image_tag.get("layers", []):
                    layer_digest = re.match(
                        r"sha256:([0-9a-f]{64})$",
                        layer.get("digest", ""),
                        re.IGNORECASE,
                    )
                    if layer_digest:
                        self._create_digest_observable(
                            image_obs, layer_digest.group(1), context, "generates"
                        )
                    file_digest = re.match(
                        r"^\w+ file:([0-9a-f]{64}) .*",
                        layer.get("instruction", ""),
                        re.IGNORECASE,
                    )
                    if file_digest:
                        self._create_digest_observable(
                            image_obs, file_digest.group(1), context, "embeds"
                        )

    def each(self, observable: Observable):
        metadata = DockerHubAPI.image_full_details(observable.value)

        if metadata is None:
            return []

        context = self._get_context(metadata)
        observable.add_context("hub.docker.com", context)
        self._make_relationships(observable, metadata)


taskmanager.TaskManager.register_task(DockerImageInspect)
