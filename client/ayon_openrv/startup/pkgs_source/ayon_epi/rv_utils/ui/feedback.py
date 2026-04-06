from rv import extra_commands
from rv_utils.ui.qt_utils import getQapp

APP = getQapp()

def feedback(message: str, duration: float = 3.0, process_events: bool = True):
    """Display rv feedback via `extra_commands.displayFeedback`, passing through attributes.

    Note:
        We process events before and after showing the feedback.
        This is useful most of the time, to ensure the feedback is shown at the
        right time, but can cause problems. So we have the option to disable it
        using process_events=False.

    Args:
        message: Message to display to the user.
        duration: Duration of the message being shown in seconds.
        process_events: Process events before and after showing the feedback.
    """
    if not message:
        return
    if process_events:
        APP.processEvents()
    extra_commands.displayFeedback(message, float(duration))
    if process_events:
        APP.processEvents()