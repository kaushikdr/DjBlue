import json
import mimetypes
import requests
from base64 import b64encode
from email.mime.base import MIMEBase
from email.utils import parseaddr
try:
    from urlparse import urljoin  # python 2
except ImportError:
    from urllib.parse import urljoin  # python 3

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address, DEFAULT_ATTACHMENT_MIME_TYPE

# from ..._version import __version__
from exceptions import (DJBlueError, DJBlueAPIError, DJBlueRecipientsRefused,
                           NotSerializableForSendinBlueError, NotSupportedBySendinBlueError)
from mailin import Mailin


class DjsbBackend(BaseEmailBackend):
    """
    SendinBlue API Email Backend
    """

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        super(DjsbBackend, self).__init__(**kwargs)

        try:
            self.api_key = settings.SENDIN_BLUE_ACCESS_KEY
        except AttributeError:
            raise ImproperlyConfigured("Set SENDIN_BLUE_ACCESS_KEY in settings.py to use DJBlue")

        self.api_url = getattr(settings, "SENDIN_BLUE_API_URL", "https://api.sendinblue.com/v2.0")
        if not self.api_url.endswith("/"):
            self.api_url += "/"

        self.ignore_recipient_status = getattr(settings, "SENDIN_BLUE_IGNORE_RECIPIENT_STATUS", False)
        self.session = None

    def open(self):
        """
        Ensure we have a requests Session to connect to the SendinBlue API.
        Returns True if a new session was created (and the caller must close it).
        """
        if self.session:
            return False  # already exists

        try:
            self.session = requests.Session()
        except requests.RequestException:
            if not self.fail_silently:
                raise
        else:
            self.session.headers["User-Agent"] = "DJBlue/backends" % ()
            return True

    def close(self):
        """
        Close the SendinBlue API Session unconditionally.

        (You should call this only if you called open and it returned True;
        else someone else created the session and will clean it up themselves.)
        """
        if self.session is None:
            return
        try:
            self.session.close()
        except requests.RequestException:
            if not self.fail_silently:
                raise
        finally:
            self.session = None

    def send_messages(self, email_messages):
        """
        Sends one or more EmailMessage objects and returns the number of email
        messages sent.
        """
        # pdb.set_trace()
        if not email_messages:
            return 0

        created_session = self.open()
        if not self.session:
            return 0  # exception in self.open with fail_silently

        num_sent = 0

        try:
            for message in email_messages:
                sent = self._send(message)
                if sent:
                    num_sent += 1
        finally:
            if created_session:
                self.close()

            return num_sent

    def _send(self, message):
        message.sendinblue_response = None  # until we have a response
        if not message.recipients():
            return False

        try:
            payload = self.build_send_payload(message)
            to_list = self._build_to_email_list(message)

            for user in to_list:
                payload['to'] = user
                response = self.post_to_sendinblue(payload, message)

        except DJBlueError:
            if not self.fail_silently:
                raise
            return False

        return True


    def build_send_payload(self, message):
        """Modify payload to add all message-specific options for SendinBlue send call.

        payload is a dict that will become the SendinBlue send data
        Can raise NotSupportedBySendinBlueError for unsupported options in message.
        """
        # pdb.set_trace()
        msg_dict = self._build_standard_message_dict(message)
        # self._add_sendinblue_options(message, msg_dict)
        if getattr(message, 'alternatives', None):
            self._add_alternatives(message, msg_dict)
        self._add_attachments(message, msg_dict)
        return msg_dict
        


    def post_to_sendinblue(self, payload, message):
        """Post payload to correct SendinBlue send API endpoint, and return the response.

        payload is a dict to use as SendinBlue send data
        return should be a requests.Response

        Can raise NotSerializableForSendinBlueError if payload is not serializable
        Can raise DJBlueAPIError for HTTP errors in the post
        """
       
        msg = Mailin(self.api_url,self.api_key)
        if not getattr(message, 'template_id', False):
            payload.update({'text':message.body})

            response,content = msg.send_email(payload)
        else:
            payload['to'] = payload['to'].keys()[0]
            response,content = msg.send_transactional_template(payload)

        

        # response = self.session.post(self.api_url, data=json_payload)
        if response.status != 200:
            raise DJBlueAPIError(email_message=message, payload=payload, response=response)
        return content

    
    #
    def _build_to_email_list(self,message):
        # sender = sanitize_address(message.from_email, message.encoding)
        to_list = self._make_sendinblue_to_list(message, message.to, "to")
        to_list += self._make_sendinblue_to_list(message, message.cc, "cc")
        to_list += self._make_sendinblue_to_list(message, message.bcc, "bcc")

        return to_list

    def _build_standard_message_dict(self, message):
        """Create a Sendin Blue send message struct from a Django EmailMessage.

        Builds the standard dict that Django's send_mail and send_mass_mail
        use by default. Standard text email messages sent through Django will
        still work through Sendin Blue.

        Raises NotSupportedBySendinBlueError for any standard EmailMessage
        features that cannot be accurately communicated to Sendin Blue.
        """
        msg_dict = {}
        if not getattr(message, 'template_id', False):
            sender = sanitize_address(message.from_email, message.encoding)
            from_name, from_email = parseaddr(sender)

            # to_list = self._make_sendinblue_to_list(message, message.to, "to")
            # to_list += self._make_sendinblue_to_list(message, message.cc, "cc")
            # to_list += self._make_sendinblue_to_list(message, message.bcc, "bcc")

            # content = "html" if message.content_subtype == "html" else "text"
            # msg_dict = {
            #     # content: message.body,
            #     "to": to_list,
            #     "cc": cc_list,
            #     "bcc": bcc_list
            # }
            

            if not getattr(message, 'use_template_from', False):
                # if from_name:
                msg_dict["from"] = [from_email,from_name or from_email.split('@')[0]]

            if not getattr(message, 'use_template_subject', False):
                msg_dict["subject"] = message.subject
        else:
            msg_dict["id"] = message.template_id
            if getattr(message, 'global_merge_vars', False):
                msg_dict['attr'] = message.global_merge_vars


        return msg_dict


    def _make_sendinblue_to_list(self, message, recipients, recipient_type="to"):
        """Create a Sendin Blue 'to' field from a list of emails.

        Parses "Real Name <address@example.com>" format emails.
        Sanitizes all email addresses.
        """
        parsed_rcpts = [parseaddr(sanitize_address(addr, message.encoding))
                        for addr in recipients]
        # return [{"email": to_email, "name": to_name, "type": recipient_type}
        #         for (to_name, to_email) in parsed_rcpts]
        return [{to_email: to_name or to_email.split('@')[0]}
                for (to_name, to_email) in parsed_rcpts]


    def _add_alternatives(self, message, msg_dict):
        """
        There can be only one! ... alternative attachment, and it must be text/html.

        Since sendinblue does not accept image attachments or anything other
        than HTML, the assumption is the only thing you are attaching is
        the HTML output for your email.
        """
        if len(message.alternatives) > 1:
            raise NotSupportedBySendinBlueError(
                "Too many alternatives attached to the message. "
                "SendinBlue only accepts plain text and html emails.",
                email_message=message)

        (content, mimetype) = message.alternatives[0]
        if mimetype != 'text/html':
            raise NotSupportedBySendinBlueError(
                "Invalid alternative mimetype '%s'. "
                "SendinBlue only accepts plain text and html emails."
                % mimetype,
                email_message=message)

        msg_dict['html'] = content

    def _add_attachments(self, message, msg_dict):
        """Extend msg_dict to include any attachments in message"""
        # pdb.set_trace()
        if message.attachments:
            str_encoding = message.encoding or settings.DEFAULT_CHARSET
            sendinblue_attachments = {}
            sendinblue_embedded_images = {}
            for attachment in message.attachments:
                att_dict, is_embedded = self._make_sendinblue_attachment(attachment, str_encoding)
                if is_embedded:
                    sendinblue_embedded_images.update(att_dict)
                else:
                    sendinblue_attachments.update(att_dict)
            if len(sendinblue_attachments) > 0:
                msg_dict['attachment'] = sendinblue_attachments
            if len(sendinblue_embedded_images) > 0:
                msg_dict['inline_image'] = sendinblue_embedded_images

    def _make_sendinblue_attachment(self, attachment, str_encoding=None):
        """Returns EmailMessage.attachments item formatted for sending with SendinBlue.

        Returns sendinblue_dict, is_embedded_image:
        sendinblue_dict: {"type":..., "name":..., "content":...}
        is_embedded_image: True if the attachment should instead be handled as an inline image.

        """
        # Note that an attachment can be either a tuple of (filename, content,
        # mimetype) or a MIMEBase object. (Also, both filename and mimetype may
        # be missing.)
        is_embedded_image = False
        if isinstance(attachment, MIMEBase):
            name = attachment.get_filename()
            content = attachment.get_payload(decode=True)
            mimetype = attachment.get_content_type()
            # Treat image attachments that have content ids as embedded:
            if attachment.get_content_maintype() == "image" and attachment["Content-ID"] is not None:
                is_embedded_image = True
                name = attachment["Content-ID"]
        else:
            (name, content, mimetype) = attachment

        # Guess missing mimetype from filename, borrowed from
        # django.core.mail.EmailMessage._create_attachment()
        if mimetype is None and name is not None:
            mimetype, _ = mimetypes.guess_type(name)
        if mimetype is None:
            mimetype = DEFAULT_ATTACHMENT_MIME_TYPE

        # b64encode requires bytes, so let's convert our content.
        try:
            # noinspection PyUnresolvedReferences
            if isinstance(content, unicode):
                # Python 2.X unicode string
                content = content.encode(str_encoding)
        except NameError:
            # Python 3 doesn't differentiate between strings and unicode
            # Convert python3 unicode str to bytes attachment:
            if isinstance(content, str):
                content = content.encode(str_encoding)

        content_b64 = b64encode(content)
        sendinblue_attachment = {
            name: content_b64.decode('ascii'),
        }

        return sendinblue_attachment, is_embedded_image
