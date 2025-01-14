import re
import os
import traceback
import json
from urllib.parse import parse_qs
from PyQt5.QtCore import QSize
from qgis.core import (QgsProject,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,
                       QgsMapLayer,
                       QgsPalLayerSettings,
                       QgsSvgMarkerSymbolLayer,
                       QgsSymbolLayerUtils,
                       QgsMessageLog,
                       Qgis,
                       QgsWkbTypes)
from qgis2web.utils import scaleToZoom, safeName


def jsonScript(layer):
    json = """
        <script src="data/{layer}.js\"></script>""".format(layer=layer)
    return json


def scaleDependentLayerScript(layer, layerName, cluster):
    max = layer.minimumScale()
    min = layer.maximumScale()
    if cluster:
        layerType = "cluster"
    else:
        layerType = "layer"
    scaleDependentLayer = """
            if (map.getZoom() <= {min} && map.getZoom() >= {max}) {{
                map.addLayer({layerType}_{layerName});
            }} else if (map.getZoom() > {min} || map.getZoom() < {max}) {{
                map.removeLayer({layerType}_{layerName});
            }}""".format(min=scaleToZoom(min), max=scaleToZoom(max),
                         layerName=layerName, layerType=layerType)
    return scaleDependentLayer


def scaleDependentLabelScript(layer, layerName):
    if layer.labeling() is not None:
        labelling = layer.labeling().settings()
        sv = labelling.scaleVisibility
        if sv:
            min = scaleToZoom(labelling.minimumScale)
            max = scaleToZoom(labelling.maximumScale)
            scaleDependentLabel = """
                if (map.hasLayer(layer_%(layerName)s)) {
                    if (map.getZoom() <= %(min)d && map.getZoom() >= %(max)d) {
                        layer_%(layerName)s.eachLayer(function (layer) {
                            layer.openTooltip();
                        });
                    } else {
                        layer_%(layerName)s.eachLayer(function (layer) {
                            layer.closeTooltip();
                        });
                    }
                }""" % {"min": min, "max": max, "layerName": layerName}
            return scaleDependentLabel
        else:
            return ""
    else:
        return ""


def scaleDependentScript(layers):
    scaleDependent = """
        map.on("zoomend", function(e) {"""
    scaleDependent += layers
    scaleDependent += """
        });"""
    scaleDependent += layers
    return scaleDependent


def highlightScript(highlight, popupsOnHover, highlightFill):
    highlightScript = """
        var highlightLayer;
        function highlightFeature(e) {
            highlightLayer = e.target;"""
    if highlight:
        highlightScript += """

            if (e.target.feature.geometry.type === 'LineString') {
              highlightLayer.setStyle({
                color: '""" + highlightFill + """',
              });
            } else {
              highlightLayer.setStyle({
                fillColor: '""" + highlightFill + """',
                fillOpacity: 1
              });
            }"""
    if popupsOnHover:
        highlightScript += """
            highlightLayer.openPopup();"""
    highlightScript += """
        }"""
    return highlightScript


def crsScript(crsAuthId, crsProj4):
    crs = """
        var crs = new L.Proj.CRS('{crsAuthId}', '{crsProj4}', {{
            resolutions: [2800, 1400, 700, 350, """.format(crsAuthId=crsAuthId,
                                                           crsProj4=crsProj4)
    crs += """175, 84, 42, 21, 11.2, 5.6, 2.8, 1.4, 0.7, 0.35, 0.14, 0.07],
        });"""
    return crs


def mapScript(extent, matchCRS, crsAuthId, measure, maxZoom, minZoom, bounds,
              locate):
    map = """
        var map = L.map('map', {"""
    if matchCRS and crsAuthId != 'EPSG:4326':
        map += """
            crs: crs,
            continuousWorld: false,
            worldCopyJump: false, """
    map += """
            zoomControl:true, maxZoom:""" + unicode(maxZoom)
    map += """, minZoom:""" + unicode(minZoom) + """
        })"""
    if extent == "Canvas extent":
        map += """.fitBounds(""" + bounds + """);"""
    map += """
        var hash = new L.Hash(map);"""
    map += """
        map.attributionControl.addAttribution('<a href="""
    map += """"https://github.com/tomchadwin/qgis2web" target="_blank">"""
    map += "qgis2web</a>');"
    if locate:
        map += """
        L.control.locate().addTo(map);"""
    if measure != "None":
        if measure == "Imperial":
            options = """{
            position: 'topleft',
            primaryLengthUnit: 'feet',
            secondaryLengthUnit: 'miles',
            primaryAreaUnit: 'sqfeet',
            secondaryAreaUnit: 'sqmiles'
        }"""
        else:
            options = """{
            position: 'topleft',
            primaryLengthUnit: 'meters',
            secondaryLengthUnit: 'kilometers',
            primaryAreaUnit: 'sqmeters',
            secondaryAreaUnit: 'hectares'
        }"""
        map += """
        var measureControl = new L.Control.Measure(%s);
        measureControl.addTo(map);
        document.getElementsByClassName('leaflet-control-measure-toggle')[0]
        .innerHTML = '';
        document.getElementsByClassName('leaflet-control-measure-toggle')[0]
        .className += ' fas fa-ruler';
        """ % options
    return map


def featureGroupsScript():
    featureGroups = """
        var bounds_group = new L.featureGroup([]);"""
    return featureGroups


def extentScript(extent, restrictToExtent):
    layerOrder = """
        function setBounds() {"""
    if extent == 'Fit to layers extent':
        layerOrder += """
            if (bounds_group.getLayers().length) {
                map.fitBounds(bounds_group.getBounds());
            }"""
    if restrictToExtent:
        layerOrder += """
            map.setMaxBounds(map.getBounds());"""
    layerOrder += """
        }"""
    return layerOrder


def popFuncsScript(table):
    popFuncs = """
            var popupContent = %s;
            layer.bindPopup(popupContent, {maxHeight: 400});""" % table
    return popFuncs


def popupScript(safeLayerName, popFuncs, highlight, popupsOnHover):
    sln = "lyr_%s_0" % safeLayerName
    popup = """
map.on('click', '%s', function (e) {
    
    let f = map.queryRenderedFeatures(e.point);
    if (f.length) {
        if(f[0].layer.id != '%s'){
            return;
        } 
    } else {
        return;
    }


    var description = %s

    new mapboxgl.Popup()
        .setLngLat(e.lngLat)
        .setHTML(description)
        .addTo(map);
});

// Change the cursor to a pointer when the mouse is over the places layer.
map.on('mouseenter', '%s', function () {
    map.getCanvas().style.cursor = 'pointer';
});

// Change it back to a pointer when it leaves.
map.on('mouseleave', '%s', function () {
    map.getCanvas().style.cursor = '';
});

""" % (sln, sln, popFuncs, sln, sln)
    return popup


def iconLegend(symbol, catr, outputProjectFileName, layerName, catLegend, cnt):
    try:
        iconSize = (symbol.size() * 4) + 5
    except:
        iconSize = 16
    legendIcon = QgsSymbolLayerUtils.symbolPreviewPixmap(symbol,
                                                         QSize(iconSize,
                                                               iconSize))
    safeLabel = re.sub(r'[\W_]+', '', catr.label()) + unicode(cnt)
    legendIcon.save(os.path.join(outputProjectFileName, "legend",
                                 layerName + "_" + safeLabel + ".png"))
    catLegend += """<tr><td style="text-align: center;"><img src="legend/"""
    catLegend += layerName + "_" + safeLabel + """.png" /></td><td>"""
    catLegend += catr.label().replace("'", "\\'") + "</td></tr>"
    return catLegend


def pointToLayerFunction(safeLayerName, sl):
    try:
        if isinstance(sl, QgsSvgMarkerSymbolLayerV2):
            markerType = "marker"
        elif sl.shape() == 8:
            markerType = "circleMarker"
        else:
            markerType = "shapeMarker"
    except:
        markerType = "circleMarker"
    pointToLayerFunction = """
        function pointToLayer_{safeLayerName}_{sl}(feature, latlng) {{
            var context = {{
                feature: feature,
                variables: {{}}
            }};
            return L.{markerType}(latlng, style_{safeLayerName}_{sl}""".format(
        safeLayerName=safeLayerName, sl=sl, markerType=markerType)
    pointToLayerFunction += """(feature));
        }"""
    return pointToLayerFunction


def wfsScript(scriptTag):
    wfs = """
        <script src='{scriptTag}'></script>""".format(scriptTag=scriptTag)
    return wfs


def clusterScript(safeLayerName):
    cluster = """
        var cluster_"""
    cluster += "{safeLayerName} = ".format(safeLayerName=safeLayerName)
    cluster += """new L.MarkerClusterGroup({{showCoverageOnHover: false,
            spiderfyDistanceMultiplier: 2}});
        cluster_{safeLayerName}""".format(safeLayerName=safeLayerName)
    cluster += """.addLayer(layer_{safeLayerName});
""".format(safeLayerName=safeLayerName)
    return cluster


def wmsScript(layer, safeLayerName, count):
    d = parse_qs(layer.source())
    opacity = layer.renderer().opacity()
    if 'type' in d and d['type'][0] == "xyz":
        wms = """
        {
            "id": "lyr_%s_%d",
            "type": "raster",
            "source": "%s"
        }""" % (safeLayerName, count, safeLayerName)
    elif 'tileMatrixSet' in d:
        useWMTS = True
        wmts_url = d['url'][0]
        wmts_layer = d['layers'][0]
        wmts_format = d['format'][0]
        wmts_crs = d['crs'][0]
        wmts_style = d['styles'][0]
        wmts_tileMatrixSet = d['tileMatrixSet'][0]
        wms = """
        var overlay_{safeLayerName} = L.tileLayer.wmts('{wmts_url}', {{
            layer: '{wmts_layer}',
            tilematrixSet: '{wmts_tileMatrixSet}',
            format: '{wmts_format}',
            style: '{wmts_style}',
            uppercase: true,
            transparent: true,
            continuousWorld : true,
            opacity: {opacity}
        }});""".format(safeLayerName=safeLayerName, wmts_url=wmts_url,
                       wmts_layer=wmts_layer, wmts_format=wmts_format,
                       wmts_tileMatrixSet=wmts_tileMatrixSet,
                       wmts_style=wmts_style, opacity=opacity)
    else:
        useWMS = True
        wms_url = d['url'][0]
        wms_layer = d['layers'][0]
        wms_format = d['format'][0]
        getFeatureInfo = ""
        if not identify:
            getFeatureInfo = """,
            identify: false,"""
        wms = """
        var overlay_%s = L.WMS.layer("%s", "%s", {
            format: '%s',
            uppercase: true,
            transparent: true,
            continuousWorld : true,
            tiled: true,
            info_format: 'text/html',
            opacity: %d%s
        });""" % (safeLayerName, wms_url, wms_layer, wms_format, opacity,
                  getFeatureInfo)
    return wms


def rasterScript(layer, safeLayerName, count):
    raster = """
        {
            "id": "lyr_%s_%d",
            "type": "raster",
            "source": "%s",
            "minzoom": 0,
            "maxzoom": 22
        }""" % (safeLayerName, count, safeLayerName)
    return raster


def titleSubScript(webmap_head):
    titleSub = "var titleData = " + json.dumps(webmap_head).replace("'", "\\'") + ";"
    return titleSub


def addLayersList(basemapList, matchCRS, layer_list, groups, cluster, legends,
                  collapsed):

    groupedLayers = {}
    for group, groupLayers in groups.items():
        groupLayerObjs = ""
        groupList = []
        groupedLayers[group] = groupList

    layerName_list = []
    layer_abstracts = {}
    layer_legends = {}

    

    for ct, layer in enumerate(layer_list):
        
        layer_id = ("lyr_%s_%d_0") % (safeName(layer.name()), ct)

        found = False

        legendHTML = ("<div class=\"menu-legend\">" + legends[safeName(layer.name()) + "_" + str(ct)] + "</div>")


        layer_abstracts[layer_id] = layer.metadata().abstract()
        layer_legends[layer_id] = legendHTML

        for group, groupLayers in groups.items():
            for layer2 in groupLayers:
                if layer == layer2:

                    sln2 = layer.name()
                    
                    groupedLayers[group].insert(0, sln2)
                    groupedLayers[group].insert(0, layer_id)

                    QgsMessageLog.logMessage("layer found in group: " + layer.name())
                    found = True
                    break
            
            if found == True: break
        if found == True: continue
        

        legendHTML = ("<div class=\"menu-legend\">" + legends[safeName(layer.name()) + "_" + str(ct)] + "</div>")
        sln = ("'%s', '%s'") % (layer_id, layer.name())
        layerName_list.insert(0, sln)

    


    layersList = """
    map.on('load', function(){
        var toggleableLayerIds = [%s];
        var toggleableGroups = %s;
        var layerLegends = %s;
        var layerAbstracts = %s;

        function ShowInfoClick(e){
            e.preventDefault();
            e.stopPropagation();

            var id = $(this).attr("layerId");
            var name = $(this).attr("layerName");
            if(!($('#modal-details-content').length == 0)) {
                $('#modal-details-content').empty();
                $('#modal-details-text').empty();
                $('#modal-details-holder').css("maxWidth","800px");
                $('#modal-details-content').html("<h3>"+name+"</h3><div>" + layerAbstracts[id].replace(/\\n/g, "<br />") + '</div><div class="pt-5"><h6>Legenda</h6>' +layerLegends[id]+ "</div>");
                $("#modal-details").modal('show');
            } else {
                console.log("Trying to show info of layer, but modal does not exist.");
            }
        }

        function ToggleLayer(e){
            var clickedLayer = this.layer;
            e.preventDefault();
            e.stopPropagation();

            var visibility = map.getLayoutProperty(clickedLayer, 'visibility');

            if (typeof visibility === 'undefined' || visibility == 'visible') {
                map.setLayoutProperty(clickedLayer, 'visibility', 'none');
                this.className = '';
            } else {
                this.className = 'active';
                map.setLayoutProperty(clickedLayer, 'visibility', 'visible');
            }
        }

        function CreateLink(id,layerName){

            var hasAbstract = false;
            if(layerAbstracts[id]) hasAbstract = true;

            var link2 = document.createElement('a');
            link2.href = '#';
            var visibility = map.getLayoutProperty(id, 'visibility');
            if(visibility == 'visible') link2.className = 'active';
            link2.layer = id;

            if(hasAbstract) link2.innerHTML = "<p>" + layerName + '<i class="fas fa-info-circle"></i></p>' + layerLegends[id];
            else link2.innerHTML = "<p>" + layerName + "</p>" + layerLegends[id];

            link2.onclick = ToggleLayer;

            if(hasAbstract){
                var infoLink = $(link2).find('i');
                infoLink.attr("layerId",id);
                infoLink.attr("layerName",layerName);

                infoLink.click(ShowInfoClick);
            }

            return link2;
        }

        var layers = document.getElementById('menu');

        for (var i = 0; i < toggleableLayerIds.length; i=i+2) {
            var id = toggleableLayerIds[i];
            var layerName = toggleableLayerIds[i+1]

            var link = CreateLink(id,layerName);

            layers.appendChild(link);
        }

        for (var groupName in toggleableGroups) {
            console.log(groupName);

            let link = document.createElement('a');
            link.href = '#';
            var visibility = map.getLayoutProperty(toggleableGroups[groupName][0], 'visibility');
            if(visibility == 'visible') link.className = 'active';
            link.innerHTML = "<p>" + groupName + "</p>";

            // Group click
            link.onclick = function (e) {
                e.preventDefault();
                e.stopPropagation();

                if(this.className == "active"){
                    this.className = "";
                    for(var j = 0; j < link.children.length; j++){
                        link2 = link.children[j];
                        map.setLayoutProperty(link2.layer, 'visibility', 'none');
                    }
                } 
                else{
                    this.className = "active";
                    for(var j = 0; j < link.children.length; j++){
                        link2 = link.children[j];
                        if(link2.className == "active"){
                            map.setLayoutProperty(link2.layer, 'visibility', 'visible');
                        }
                    }
                }  
            };
            var layers = document.getElementById('menu');
            layers.appendChild(link);

            //actual layer in group
            for (var i = 0; i < toggleableGroups[groupName].length; i=i+2) {

                var id = toggleableGroups[groupName][i];
                var layerName = toggleableGroups[groupName][i+1]

                var link2 = CreateLink(id,layerName);
                
                link.appendChild(link2);
            }
        }
    });""" % (",".join(layerName_list), json.dumps(groupedLayers), json.dumps(layer_legends), json.dumps(layer_abstracts))

    return layersList


def scaleBar():
    scaleBar = "L.control.scale({position: 'bottomleft', "
    scaleBar += "maxWidth: 100, metric: true, imperial: false, "
    scaleBar += "updateWhenIdle: false}).addTo(map);"
    return scaleBar


def addressSearchScript():
    addressSearch = """
        var geocodeNominatimRequest = function(query, mapBounds, options) {
        var params = { format: "json", q: query, limit: options.limit };
        var urlParams = new URLSearchParams(Object.entries(params));

        return fetch("https://nominatim.openstreetmap.org/search?" + urlParams)
            .then(function(response) {
                if(response.ok) {
                    return response.json();
                } else {
                    return [];
                }
            }).then(function(json) {
                return json.map(function(result) {
                    return {
                        name: result.display_name,
                        lat: result.lat,
                        lon: result.lon,
                        bbox: [result.boundingbox[2], result.boundingbox[0],
                               result.boundingbox[3], result.boundingbox[1]]
                    };
                });
            });
        };

        map.addControl(new MapboxGenericGeocoder({}, geocodeNominatimRequest));
"""
    return addressSearch


def getVTStyles(vtStyles):
    vtStyleString = ""
    for (vts, lyrs) in vtStyles.items():
        vtStyleString += """
        style_%s = {""" % safeName(vts)
        for (lyr, styles) in lyrs.items():
            vtStyleString += """
            %s: [""" % lyr
            for style in styles:
                if style == "":
                    style = "{}"
                vtStyleString += "%s," % style
            vtStyleString += "],"
            vtStyleString = vtStyleString.replace(",]", "]")
        vtStyleString += "}"

    return vtStyleString


def getVTLabels(vtLabels):
    labels = []
    for k, v in vtLabels.items():
        labels.append("""
    function label_%s(feature, featureLayer, vtLayer, tileCoords) {
        var context = {
            feature: feature,
            variables: {}
        };
        %s
    }""" % (safeName(k), v))
    labelString = "".join(labels)
    return labelString


def endHTMLscript(wfsLayers, layerSearch, labelCode, labels, searchLayer,
                  useHeat, useRaster, labelsList, mapUnitLayers):
    if labels == "":
        endHTML = ""
    else:
        endHTML = """
        map.on("zoomend", function(){
%s
        });""" % labels
    if wfsLayers == "":
        endHTML += """
        setBounds();
        %s""" % labelCode
        endHTML += labels
    if len(mapUnitLayers) > 0:
        lyrs = []
        for layer in mapUnitLayers:
            lyrs.append("""
            layer_%s.setStyle(style_%s_0);""" % (layer, layer))
        lyrScripts = "".join(lyrs)
        endHTML += """
        newM2px();
%s
        map.on("zoomend", function(){
            newM2px();
%s
        });""" % (lyrScripts, lyrScripts)
    if layerSearch != "None":
        searchVals = layerSearch.split(": ")
        endHTML += """
        map.addControl(new L.Control.Search({{
            layer: {searchLayer},
            initial: false,
            hideMarkerOnCollapse: true,
            propertyName: '{field}'}}));
        document.getElementsByClassName('search-button')[0].className +=
         ' fa fa-binoculars';
            """.format(searchLayer=searchLayer,
                       field=searchVals[1])
    if useHeat:
        endHTML += """
        function geoJson2heat(geojson, weight) {
          return geojson.features.map(function(feature) {
            return [
              feature.geometry.coordinates[1],
              feature.geometry.coordinates[0],
              feature.properties[weight]
            ];
          });
        }"""
    if useRaster:
        endHTML += """
        L.ImageOverlay.include({
            getBounds: function () {
                return this._bounds;
            }
        });"""
    if labelsList != "":
        endHTML += """
        resetLabels([%s]);
        map.on("zoomend", function(){
            resetLabels([%s]);
        });
        map.on("layeradd", function(){
            resetLabels([%s]);
        });
        map.on("layerremove", function(){
            resetLabels([%s]);
        });""" % (labelsList, labelsList, labelsList, labelsList)
    endHTML += """
        </script>%s""" % wfsLayers
    return endHTML
