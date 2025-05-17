"""
Exceptions for Cynthia.
"""


class CynthiaException(BaseException):
    """
    Generic Cynthia-Specific Exception.
    """

    pass


class NonFatalCynException(CynthiaException):
    """
    Generic NonFatal Exception. Presumably unexpected.
    """

    pass


class FatalCynException(CynthiaException):
    """
    Generic Fatal Exception. Presumably unexpected unless XFatal is raised.
    """

    pass


class XFatalCynException(FatalCynException):
    """
    Expected Fatal Exception (ie. deliberate exit)
    """

    pass


class ExitCynthia(XFatalCynException):
    """
    Raise to exit Cynthia.
    """

    pass
