$(function() {
  function linksFilter(nodeId, field) {
    return function(links) {
      return links[field] == nodeId;
    };
  }

  function enrichLink(nodeField) {
    return function(link) {
      var node = nodes.get(link[nodeField]);
      link.nodeId = node.id;
      link.cssicon = node.cssicon;
      link.value = node.label;
      link.tags = node.tags;
    };
  }

  function displayLinks(nodeId) {
    var incoming = edges.get({filter: linksFilter(nodeId, 'to')});
    incoming.forEach(enrichLink('from'));
    $('#graph-sidebar-links-to-' + nodeId).html(linksTemplate({links: incoming}));

    var outgoing = edges.get({filter: linksFilter(nodeId, 'from')});
    outgoing.forEach(enrichLink('to'));
    $('#graph-sidebar-links-from-' + nodeId).html(linksTemplate({links: outgoing}));
  }

  function displayAnalytics(nodeId, nodeType) {
    var availableAnalytics = analytics.get({
      filter: function(item) {
        return item.acts_on == nodeType;
      },
    });

    $('#graph-sidebar-analytics-' + nodeId).html(analyticsTemplate({analytics: availableAnalytics}));
  }

  function retrieveNodeNeighborsCallback(nodeId) {
    return function(data) {
      data.links.forEach(function(link) {
        if (!edges.get(link.id)) {
          link.arrows = 'to';
          edges.add(link);
        }
      });

      data.nodes.forEach(function(node) {
        if (!nodes.get(node.id)) {
          node.label = node.value;
          node.shape = 'icon';
          node.icon = icons[node.type];
          node.cssicon = cssicons[node.type];
          nodes.add(node);
        }
      });

      nodes.update({id: nodeId, fetched: true});

      displayLinks(nodeId);
    };
  }

  function retrieveNodeNeighbors(nodeId) {
    $.getJSON('/api/graph/neighbors/' + nodeId, retrieveNodeNeighborsCallback(nodeId));
  }

  function selectNode(nodeId) {
    var node = nodes.get(nodeId);

    // Update sidebar with content related to this node
    $('#graph-sidebar').html(nodeTemplate(node));

    // Display analytics
    displayAnalytics(nodeId, node.type);

    // Display links
    if (node.fetched) {
      displayLinks(nodeId);
    } else {
      retrieveNodeNeighbors(nodeId);
    }
  }

  function loadAnalytics() {
    $.getJSON('/api/analytics/oneshot', function(data) {
      data.forEach(function(item) {
        if (item.enabled) {
          analytics.add(item);
        }
      });
    });
  }

  function fetchAnalyticsResultsCallback(name, resultsId, resultsDiv, button) {
    return function() {
      return fetchAnalyticsResults(name, resultsId, resultsDiv, button);
    };
  }

  function fetchAnalyticsResults(name, resultsId, resultsDiv, button) {
    function callback(data) {
      if (data.status == 'finished') {
        var links = [];

        data.results.nodes.forEach(function(node) {
          if (!nodes.get(node._id)) {
            node.id = node._id;
            node.type = node._cls.split('.');
            node.type = node.type[nodeType.length - 1];
            node.label = node.value;
            node.shape = 'icon';
            node.icon = icons[node.type];
            node.cssicon = cssicons[node.type];

            nodes.add(node);
          }
        });

        data.results.links.forEach(function(link) {
          var existingLink = edges.get(link._id);

          if (existingLink) {
            existingLink.label = link.description;
            edges.update({id: link._id, label: link.description});

            link = existingLink;
          } else {
            link.arrows = 'to';
            link.id = link._id;
            link.from = link.src.id;
            link.to = link.dst.id;
            edges.add(link);
          }

          if (link.from == data.observable) {
            enrichLink('to')(link);
            links.push(link);
          } else if (link.to == data.observable) {
            enrichLink('from')(link);
            links.push(link);
          }
        });

        resultsDiv.html(linksTemplate({links: links}));
        button.removeClass('glyphicon-spinner');
      } else {
        setTimeout(fetchAnalyticsResultsCallback(name, resultsId, resultsDiv, button), 1000);
      }
    }

    $.post(
      '/api/analytics/oneshot/' + name + '/status',
      {id: resultsId},
      callback,
      'json'
    );
  }

  function runAnalytics(name, nodeId, resultsDiv, progress) {
    function runCallback(data) {
      var resultsId = data._id;

      fetchAnalyticsResults(name, resultsId, resultsDiv, progress);
    }

    $.post(
      '/api/analytics/oneshot/' + name + '/run',
      {id: nodeId},
      runCallback,
      'json'
    );
  }

  // Compile templates
  var nodeTemplate = Handlebars.compile($('#graph-sidebar-node-template').html());
  var linksTemplate = Handlebars.compile($('#graph-sidebar-links-template').html());
  var analyticsTemplate = Handlebars.compile($('#graph-sidebar-analytics-template').html());

  // create the observable dataset and dataview
  var nodes = new vis.DataSet([]);
  var visibleNodes = new vis.DataView(nodes, {
    filter: function(item) {
      return item.visible;
    },
  });

  // Add the first observable
  nodes.add(observable);

  // create the edges dataset and dataview
  var edges = new vis.DataSet([]);
  var visibleEdges = new vis.DataView(edges, {
    filter: function(item) {
      return item.visible;
    },
  });

  // create a network
  var container = document.getElementById('graph');
  var data = {
    nodes: visibleNodes,
    edges: visibleEdges,
  };
  var options = {
    physics: {
      barnesHut: {
        springLength: 300,
      },
    },
  };
  var network = new vis.Network(container, data, options);

  // create analytics
  var analytics = new vis.DataSet([]);
  loadAnalytics();

  network.on('selectNode', function(params) {
    selectNode(params.nodes[params.nodes.length - 1]);
  });

  $('#graph-sidebar').on('click', '.graph-sidebar-display-link', function(e) {
    linkId = $(this).data('link');
    nodeId = $(this).data('node');

    edges.update({id: linkId, visible: true});
    nodes.update({id: nodeId, visible: true});
  });

  $('#graph-sidebar').on('click', '.graph-sidebar-run-analytics', function(e) {
    button = $(this);

    name = button.data('name');
    nodeId = button.parents('#graph-sidebar-content').data('id');
    resultsDiv = button.parent().prev();

    button.addClass('glyphicon-spinner');

    runAnalytics(name, nodeId, resultsDiv, button);
  });
});
