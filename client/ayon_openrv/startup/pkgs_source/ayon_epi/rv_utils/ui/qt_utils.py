import sys

from qtpy import QtWidgets, QtCore


def getQapp():
    """get qapp QApplication instance or create new one

    tries to get QApplication if possible, else QCoreApplication (for non GUI)

    returns:
        QApplication or QCoreApplication instance
    """
    try:
        qapp = QtWidgets.QApplication.instance()
        if not qapp:
            qapp = QtWidgets.QApplication(sys.argv)
        return qapp
    except Exception:
        # can not get QApplication, get QCoreApplication instead
        pass
    qcoreapp = QtCore.QCoreApplication.instance()
    if not qcoreapp:
        qcoreapp = QtCore.QCoreApplication(sys.argv)
    return qcoreapp