import json
from requests import HTTPError


class DJBlueError(Exception):
    """Base class for exceptions raised by DJBlue

    Overrides __str__ to provide additional information about
    Sendin Blue API call and response.
    """

    def __init__(self, *args, **kwargs):
        """
        Optional kwargs:
          email_message: the original EmailMessage being sent
          payload: data arg (*not* json-stringified) for the SendinBlue send call
          response: requests.Response from the send call
        """
        self.email_message = kwargs.pop('email_message', None)
        self.payload = kwargs.pop('payload', None)
        if isinstance(self, HTTPError):
            # must leave response in kwargs for HTTPError
            self.response = kwargs.get('response', None)
        else:
            self.response = kwargs.pop('response', None)
        super(DJBlueError, self).__init__(*args, **kwargs)

    def __str__(self):
        parts = [
            " ".join([str(arg) for arg in self.args]),
            self.describe_send(),
            self.describe_response(),
        ]
        return "\n".join(filter(None, parts))

    def describe_send(self):
        """Return a string describing the SendinBlue send in self.payload, or None"""
        if self.payload is None:
            return None
        description = "Sending a message"
        try:
            to_emails = [to['email'] for to in self.payload['message']['to']]
            description += " to %s" % ','.join(to_emails)
        except KeyError:
            pass
        try:
            description += " from %s" % self.payload['message']['from_email']
        except KeyError:
            pass
        return description

    def describe_response(self):
        """Return a formatted string of self.response, or None"""
        if self.response is None:
            return None
        description = "SendinBlue API response %d:" % self.response.status
        try:
            # json_response = self.response.json()
            description += "\n" + json.dumps(self.response, indent=2)
        except (AttributeError, KeyError, ValueError):  # not JSON = ValueError
            try:
                description += " " + self.response.text
            except AttributeError:
                pass
        return description


class DJBlueAPIError(DJBlueError, HTTPError):
    """Exception for unsuccessful response from SendinBlue API."""

    def __init__(self, *args, **kwargs):
        super(DJBlueAPIError, self).__init__(*args, **kwargs)
        if self.response is not None:
            self.status = self.response.status


class DJBlueRecipientsRefused(DJBlueError):
    """Exception for send where all recipients are invalid or rejected."""

    def __init__(self, message=None, *args, **kwargs):
        if message is None:
            message = "All message recipients were rejected or invalid"
        super(DJBlueRecipientsRefused, self).__init__(message, *args, **kwargs)


class NotSupportedBySendinBlueError(DJBlueError, ValueError):
    """Exception for email features that SendinBlue doesn't support.

    This is typically raised when attempting to send a Django EmailMessage that
    uses options or values you might expect to work, but that are silently
    ignored by or can't be communicated to SendinBlue's API. (E.g., non-HTML
    alternative parts.)
    """


class NotSerializableForSendinBlueError(DJBlueError, TypeError):
    """Exception for data that DJBlue doesn't know how to convert to JSON.
    """

    def __init__(self, message=None, orig_err=None, *args, **kwargs):
        if message is None:
            message = "Don't know how to send this data to SendinBlue. " \
                      "Try converting it to a string or number first."
        if orig_err is not None:
            message += "\n%s" % str(orig_err)
        super(NotSerializableForSendinBlueError, self).__init__(message, *args, **kwargs)