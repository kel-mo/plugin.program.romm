# -*- coding: utf-8 -*-
"""Full-screen pairing dialog: QR code, short code and URL, cancellable with Back."""
import xbmcgui

from . import kodi

ACTION_CANCEL = {9, 10, 92, 216}  # parent dir, previous menu, nav back, stop


class PairDialog(xbmcgui.WindowDialog):
    def __init__(self, qr_png, background_png, url, code, expires_in):
        super().__init__()
        self.cancelled = False
        self.addControl(xbmcgui.ControlImage(0, 0, 1280, 720, background_png))
        self.addControl(xbmcgui.ControlImage(100, 140, 440, 440, qr_png, aspectRatio=2))
        x, w = 600, 600
        self.addControl(xbmcgui.ControlLabel(x, 140, w, 40, kodi.L(30005), font='font14', textColor='0xFFFFFFFF'))
        self.addControl(xbmcgui.ControlLabel(x, 200, w, 30, kodi.L(30627), font='font13', textColor='0xFFCCCCCC'))
        self.addControl(xbmcgui.ControlLabel(x, 235, w, 30, url, font='font12', textColor='0xFF8B5CF6'))
        self.addControl(xbmcgui.ControlLabel(x, 300, w, 80, code, font='font45', textColor='0xFFFFFFFF'))
        self.status = xbmcgui.ControlLabel(x, 400, w, 30, kodi.L(30603), font='font13', textColor='0xFFCCCCCC')
        self.addControl(self.status)
        self.addControl(xbmcgui.ControlLabel(x, 440, w, 30, kodi.L(30628), font='font12', textColor='0xFF888888'))
        self.progress = xbmcgui.ControlProgress(x, 490, w, 12)
        self.addControl(self.progress)
        self.progress.setPercent(100)
        self.expires_in = max(expires_in, 1)

    def tick(self, remaining):
        self.progress.setPercent(int(100 * remaining / self.expires_in))

    def set_status(self, text):
        self.status.setLabel(text)

    def onAction(self, action):
        if action.getId() in ACTION_CANCEL:
            self.cancelled = True
            self.close()
