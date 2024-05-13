# Copyright © 2024 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions andcurrent_app.
# limitations under the License.
"""Worker resource to handle incoming queue pushes from gcp."""
import sys
from http import HTTPStatus

from flask import Blueprint, request
from notify_api.models import Notification, NotificationHistory, NotificationSendResponses
from notify_api.services.gcp_queue import queue
from notify_api.utils.logging import logger

from notify_delivery.services.providers import _all_providers  # noqa: E402

bp = Blueprint("gcnotify", __name__)


@bp.route("/", methods=("POST",))
def worker():
    """Worker to handle incoming queue pushes."""
    if not request.data:
        logger.info("No incoming raw msg.")
        return {}, HTTPStatus.OK

    if not (ce := queue.get_simple_cloud_event(request, wrapped=True)):
        # Return a 200, so event is removed from the Queue
        logger.info("No incoming cloud event msg.")
        return {}, HTTPStatus.OK

    try:
        logger.info(f"Event Message Received: {ce}")
        if ce.type == "bc.registry.notify.gc_notify":
            # Delivery message through GC Notify service.
            notification_id = ce.data["notificationId"]
            notification: Notification = Notification.find_notification_by_id(notification_id)
            if notification is None:
                raise Exception(  # pylint: disable=broad-exception-raised
                    f"Unknown notification for notificationId {notification_id}"
                )

            if notification.status_code != Notification.NotificationStatus.QUEUED:
                raise Exception(  # pylint: disable=broad-exception-raised
                    f"Notification status is not {notification.status_code}"
                )

            responses: NotificationSendResponses = _all_providers[notification.provider_code](notification).send()

            if responses:
                for response in responses.recipients:
                    # save to history as per recipient
                    NotificationHistory.create_history(notification, response.recipient, response.response_id)
            else:
                NotificationHistory.create_history(notification)

            # clean notification record
            notification.delete_notification()
        else:
            raise Exception("Invalid queue message type")  # pylint: disable=broad-exception-raised

        logger.info(f"Event Message Proccessd: {ce.id}")

        return {}, HTTPStatus.OK
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error(f"Failed to process queue message: {sys.exc_info()}")
        # Optionally, return an error status code or message
        return {}, HTTPStatus.OK
