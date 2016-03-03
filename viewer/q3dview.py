# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Q3DView

                              -------------------
        begin                : 2016-02-10
        copyright            : (C) 2016 Minoru Akagi
        email                : akaginch@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from datetime import datetime
import json
import os

#from PyQt5.Qt import *
from PyQt5.QtCore import QByteArray, QBuffer, QIODevice, QObject, QUrl, Qt, pyqtSlot
#from PyQt5.QtGui import *
from PyQt5.QtWebKitWidgets import QWebPage, QWebView

import q3dconst
from socketclient import SocketClient


def base64image(image):
  ba = QByteArray()
  buffer = QBuffer(ba)
  buffer.open(QIODevice.WriteOnly)
  image.save(buffer, "PNG")
  return "data:image/png;base64," + ba.toBase64().data().decode("utf-8")


class Bridge(QObject):

  def __init__(self, layerManager, parent=None):
    QObject.__init__(self, parent)
    self._parent = parent
    self.layerManager = layerManager

  @pyqtSlot()
  def myName(self):
    return "QtWebKit Bridge Test"   # Not works

  @pyqtSlot(int, int)
  def setLayerId(self, pyLayerId, jsLayerId):
    self.layerManager.layers[pyLayerId]["jsLayerId"] = jsLayerId
    print("Layer {0} in the layer manager got a layer ID for Q3D project. Layer ID: {1}".format(pyLayerId, jsLayerId))

  @pyqtSlot(str)
  def saveImage(self, dataUrl):
    self._parent.saveImage(dataUrl)

  @pyqtSlot(str)
  def mouseUp(self, coords):
    print(coords)


class Q3DWebPage(QWebPage):

  def __init__(self, parent=None):
    QWebPage.__init__(self, parent)

    # open log file
    self.logfile = open(os.path.join(os.path.dirname(__file__), "q3dview.log"), "w")

  def javaScriptConsoleMessage(self, message, lineNumber, sourceID):
    print("[JS CONSOLE] {0} ({1}:{2})".format(message, sourceID, lineNumber))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    self.logfile.write("{0}: {1} ({2}:{3})".format(now, message, sourceID, lineNumber))


class Q3DView(QWebView):

  def __init__(self, parent=None):
    QWebView.__init__(self, parent)

    self.requestQueue = []
    self._processing = False

  def setup(self, wnd, layerManager, serverName="Qgis2threejs", isViewer=True):
    self.wnd = wnd
    self.layerManager = layerManager
    self.isViewer = isViewer
    self.iface = SocketClient(serverName, self)
    self.iface.notified.connect(self.notified)
    self.iface.requestReceived.connect(self.requestReceived)
    self.iface.responseReceived.connect(self.responseReceived)

    self._page = Q3DWebPage(self)
    self.setPage(self._page)
    self.loadFinished.connect(self.pageLoaded)

    filetitle = "viewer" if isViewer else "layer"

    # HTML file and js file for debug
    viewer_dir = os.path.dirname(__file__)
    with open(os.path.join(viewer_dir, filetitle + ".html"), "r", encoding="UTF-8") as f1:
      with open(os.path.join(viewer_dir, "debug.html"), "w", encoding="UTF-8") as f2:
        f2.write(f1.read().replace("<!--${scripts}-->", '<script src="debug.js"></script>'))

    self.jsfile = open(os.path.join(viewer_dir, "debug.js"), "w")

    url = os.path.join(os.path.abspath(os.path.dirname(__file__)), filetitle + ".html").replace("\\", "/")
    self.setUrl(QUrl.fromLocalFile(url))
    #self.setUrl(QUrl("https://dl.dropboxusercontent.com/u/21526091/qgis-plugins/samples/threejs/mt_fuji.html"))
    print("URL: {0}".format(self.url().toString()))

  def showStatusMessage(self, msg):
    self.wnd.ui.statusbar.showMessage(msg)

  def reload(self):
    pass

  def resetCameraPosition(self):
    pass

  def pageLoaded(self, ok):
    self.bridge = Bridge(self.layerManager, self)
    self._page.mainFrame().addToJavaScriptWindowObject("pyObj", self.bridge)

    self.iface.request(q3dconst.JSON_LAYER_LIST)
    if self.isViewer:
      self.iface.request(q3dconst.JS_CREATE_PROJECT)
      self.iface.request(q3dconst.JS_START_APP)

  def treeItemChanged(self, item):
    itemId = item.data()
    layer = self.layerManager.layers[itemId]
    visible = bool(item.checkState() == Qt.Checked)

    if layer["geomType"] == q3dconst.TYPE_IMAGE:    #TODO: image
      return

    layer["visible"] = visible
    if visible:
      if layer["jsLayerId"] is None:
        self.iface.request(q3dconst.JS_CREATE_LAYER, layer)
      else:
        self.runString("project.layers[{0}].setVisible(true);".format(layer["jsLayerId"]))
        self.iface.request(q3dconst.JS_UPDATE_LAYER, layer)
    else:
      self.runString("project.layers[{0}].setVisible(false);".format(layer["jsLayerId"]))

  def treeItemDoubleClicked(self, index):
    idx = index.data(Qt.UserRole + 1)
    self.iface.notify(q3dconst.N_LAYER_DOUBLECLICKED, self.layerManager.layers[idx])

  def runByteArray(self, ba):
    if os.name == "nt":
      ba = ba.replace(b"\0", b"")   # remove \0 characters at the end  #TODO: why \0 characters there?
    self.runString(ba.data().decode("utf-8"))

  def runString(self, string):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    self.jsfile.write("//// runString ({0})\n{1}\n".format(now, string))
    return self._page.mainFrame().evaluateJavaScript(string)

  def notified(self, code, params):
    print("Notification received: {0} ({1})".format(code, str(params)))

    if code == q3dconst.N_CANVAS_EXTENT_CHANGED:
      self.iface.request(q3dconst.JS_UPDATE_PROJECT)

    elif code == q3dconst.N_CANVAS_IMAGE_UPDATED:
      for layer in self.layerManager.layers:
        if layer["visible"]:
          self.iface.request(q3dconst.JS_UPDATE_LAYER, layer)

    elif code == q3dconst.N_LAYER_PROPERTIES_CHANGED:
      layer = self.layerManager.layers[params["id"]]
      layer["properties"] = params["properties"]
      self.iface.request(q3dconst.JS_UPDATE_LAYER, layer)

  def requestReceived(self, dataType, params):
    #TODO: remove any duplicate requests in requestQueue if the request is sent to update 3d model (e.g. JS_UPDATE_LAYER).
    self.requestQueue.append([dataType, params])
    if not self._processing:
      self.processNextRequest()

  def responseReceived(self, data, dataType):
    if dataType == q3dconst.JS_UPDATE_LAYER:
      print("JS_UPDATE_LAYER data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JS_UPDATE_PROJECT:
      print("JS_UPDATE_PROJECT data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JS_CREATE_LAYER:
      print("JS_CREATE_LAYER data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JS_CREATE_PROJECT:
      print("JS_CREATE_PROJECT data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JS_SAVE_IMAGE:
      print("JS_SAVE_IMAGE data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JS_START_APP:
      print("JS_START_APP data received.")
      self.runByteArray(data)

    elif dataType == q3dconst.JSON_LAYER_LIST:
      if os.name == "nt":
        data = data.replace(b"\0", b"")   # remove \0 characters at the end  #TODO: why \0 characters there?

      layers = json.loads(data.data().decode("utf-8"))
      for idx, layer in enumerate(layers):
        self.layerManager.addLayer(layer["layerId"], layer["name"], layer["geomType"], idx == 0, layer.get("properties"))    #TODO: check "visible"

      for layer in self.layerManager.layers:
        if layer["visible"]:
          self.iface.request(q3dconst.JS_CREATE_LAYER, layer)

  def processNextRequest(self):
    if self._processing or len(self.requestQueue) == 0:
      return
    dataType, params = self.requestQueue.pop(0)
    self._processing = True
    if not self.processRequest(dataType, params):
      self._processing = False
      self.processNextRequest()

  def processRequest(self, dataType, params):
    if dataType == q3dconst.BIN_SCENE_IMAGE:
      extent = params["baseExtent"]
      js = """project.update({{
baseExtent: [{}, {}, {}, {}],
rotation: {}
}});
""".format(extent[0], extent[1], extent[2], extent[3], params["rotation"])
      self.runString(js)

      #self.iface.request(q3dconst.JS_UPDATE_PROJECT)
      for layer in self.layerManager.layers:
        if layer["visible"] and layer["jsLayerId"] is not None:
          self.iface.request(q3dconst.JS_UPDATE_LAYER, layer)
      self.iface.request(q3dconst.JS_SAVE_IMAGE, {"width": params["width"], "height": params["height"]})
      return True
    return False

  def saveImage(self, dataUrl):
    ba = QByteArray.fromBase64(dataUrl[22:].encode("ascii"))
    self.iface.respond(ba, q3dconst.BIN_SCENE_IMAGE)    # q3dconst.FORMAT_BINARY

    self._processing = False
    self.processNextRequest()
