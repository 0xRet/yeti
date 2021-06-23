from os import link, name
import whois
from core.analytics import OneShotAnalytics
from core.common.utils import tldextract_parser
from core.observables import Email, Text, Hostname, email
from core.entities import Company, company


def link_from_contact_info(hostname, contact, field, klass, description):
    if contact is not None and field in contact:
        if klass == Text:
            node = klass.get_or_create(value=contact[field])
            node.update(record_type=field)
        else:
            node = klass.get_or_create(value=contact[field])

        return hostname.active_link_to(node, description, "Whois")
    else:
        return ()


class Whois(OneShotAnalytics):

    default_values = {
        "name": "Whois",
        "description": "Perform a Whois request on the domain name and tries to"
        " extract relevant information.",
    }

    ACTS_ON = "Hostname"

    @staticmethod
    def analyze(hostname, results):
        links = set()
        data = whois.whois(hostname.value)
        if not data["domain_name"]:
            return list(links)
        should_add_context = False

        for context in hostname.context:
            if context["source"] == "whois":
                break
        else:
            should_add_context = True
            context = {"source": "whois"}
            context["whois_server"] = data["whois_server"]
            if data["dnssec"]:
                context["dnssec"] = data["dnssec"]

            if type(data["creation_date"]) is list:
                context["creation_date"] = sorted(data["creation_date"])[0]
            else:
                context["creation_date"] = data["creation_date"]

            if type(data["updated_date"]) is list:
                context["updated_date"] = sorted(data["updated_date"], reverse=True)[0]
            else:
                context["updated_date"] = data["updated_date"]

            if type(data["expiration_date"]) is list:
                context["expiration_date"] = sorted(
                    data["expiration_date"], reverse=True
                )[0]
            else:
                context["expiration_date"] = data["expiration_date"]

            name_servers = data["name_servers"]

        if type(name_servers) is list:
            for ns in name_servers:
                ns_obs = Hostname.get_or_create(value=ns)
                links.update(ns_obs.active_link_to(hostname, "NS", context["source"]))
        else:
            ns_obs = Hostname.get_or_create(value=name_servers)
            links.update(ns_obs.active_link_to(hostname, "NS", context["source"]))

        for email in data["emails"]:
            email_obs = Email.get_or_create(value=email)
            links.update(
                email_obs.active_link_to(hostname, "email registrar", context["source"])
            )
        if data["org"]:
            company = Company.get_or_create(name=data["org"])
            company.active_link_to(hostname, "Org", context["source"])

        if data["registrar"]:
            company = Company.get_or_create(name=data["registrar"])
        if should_add_context:
            hostname.add_context(context)
        else:
            hostname.save()

        return list(links)
