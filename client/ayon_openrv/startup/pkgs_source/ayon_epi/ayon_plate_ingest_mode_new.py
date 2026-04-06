"""Mode to ingest plates into AYON using RV."""
from __future__ import annotations

from PySide2 import QtCore

from ingest_assistant_new import IngestAssistant
from rv import commands, rvtypes, qtutils, extra_commands, runtime
from rv.commands import nodeType, nodeGroup


class AyonPlateIngest2(rvtypes.MinorMode):
    """Mode for ingesting plates into AYON."""

    def __init__(self):
        super().__init__()

        bindings = [
            (
                "key-down--alt--[",
                self.mark_in,
                "Start Marking at frame"
            ),
            (
                "key-down--alt--]",
                self.mark_out,
                "End Marking at frame"
            ),
            (
                "mark-unmark-event",
                self.mark_frames,
                "Mark/Unmark selected frames"
            )
        ]
        menu = [
            (
                "AYON Ingest",
                [
                    (
                        "Make all source Pixel Aspect 1.5",
                        self.set_pixel_aspect,
                        None,
                        None
                    ),
                    (
                        "Mark Frame",
                        self.mark_in,
                        "m",
                        None
                    ),
                    (
                        "Start Marking at Frame",
                        self.mark_in,
                        "Alt+[",
                        None
                    ),
                    (
                        "End Marking at Frame",
                        self.mark_out,
                        "Alt+]",
                        None
                    )
                ]
            )
        ]

        self.init("AYON Plate Ingest", bindings, None, menu)

        self._frames_mark_start = -1
        self._frames_mark_end = -1
        self.assistant = IngestAssistant()
        qtutils.sessionWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, self.assistant)

    def activate(self):
        """Activate the mode."""
        super().activate()
        self.assistant.show()

    def deactivate(self):
        """Deactivate the mode."""
        super().deactivate()
        self.assistant.hide()

    def set_pixel_aspect(self, event=None):
        """Set pixel aspect ratio for all source nodes to 1.5."""
        for node in commands.nodesOfType("RVLensWarp"):
            if nodeType(nodeGroup(nodeGroup(node))) == "RVSourceGroup":
                commands.setFloatProperty(node + ".warp.pixelAspectRatio", [1.5])

    def mark(self, event=None):
        """Toggle mark on the current frame."""
        cur_frame = commands.frame()
        is_marked = commands.isMarked(cur_frame)
        commands.markFrame(cur_frame, not is_marked)

    def mark_in(self, event=None):
        """Mark frames if the frame end was selected first or save frame start."""
        cur_frame = commands.frame()
        end = self._frames_mark_end

        self._frames_mark_start = cur_frame

        if end <= 0 or cur_frame > end:
            # If the end frame is not set or the current frame is after the end frame
            extra_commands.displayFeedback2(f"Start marking at Frame {cur_frame}", 5.0)
            return

        self.get_user_input()

    def mark_out(self, event=None):
        """Mark frames if the frame start was selected first or save frame end."""
        cur_frame = commands.frame()
        start = self._frames_mark_start

        self._frames_mark_end = cur_frame

        if start <= 0 or cur_frame < start:
            # If the start frame is not set or the current frame is before the start frame
            extra_commands.displayFeedback2(f"End marking at Frame {cur_frame}", 5.0)
            return

        self.get_user_input()

    def get_user_input(self):
        """Get user input if we should mark or unmark framerange."""
        runtime.eval(
            r"""
                {
                    \: eventSender (void; string text)
                    {
                        string result = "";
                        if ((text == "") || (text == "m") || (text == "M")) result = "true";
                        if ((text == "u") || (text == "U")) result = "false";
                        let returnValue = sendInternalEvent("mark-unmark-event", result);
                        redraw();
                    }

                    rvui.startTextEntryMode(\: (string;) { "Mark/Unmark Frames %s-%s (M/u): ";}, eventSender, true)(nil);
                }
            """ % (self._frames_mark_start, self._frames_mark_end),
            ["rvui", "commands"],
        )

    def mark_frames(self, event):
        """Mark or unmark current selected frame range."""
        contents = event.contents()
        if not contents:
            return
        mark = contents == "true"
        for frame in range(self._frames_mark_start, self._frames_mark_end + 1):
            commands.markFrame(frame, mark)

        self._frames_mark_start = -1
        self._frames_mark_end = -1

def createMode():  # noqa
    """Required to initialize the module. RV will call this function to create the mode."""
    return AyonPlateIngest2()