"""A click-through cyan tint; visible only while explicit screen access is active."""

from __future__ import annotations


class ScreenOverlay:
    def __init__(self) -> None:
        self._window = None

    def show(self) -> None:
        if self._window is not None:
            return
        from AppKit import (
            NSBackingStoreBuffered,
            NSColor,
            NSFloatingWindowLevel,
            NSScreen,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowStyleMaskBorderless,
        )

        # Match screencapture -m / CGMainDisplayID, not the keyboard-active display.
        screens = NSScreen.screens()
        screen = screens[0] if screens else None
        if screen is None:
            raise RuntimeError("No display is available for the screen-access indicator.")
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            screen.frame(),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.05,
                0.7,
                1.0,
                0.065,
            )
        )
        window.setHasShadow_(False)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(NSFloatingWindowLevel)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setReleasedWhenClosed_(False)
        window.orderFrontRegardless()  # Never make key or take keyboard focus.
        self._window = window

    def hide(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)
            self._window.close()
            self._window = None
