"""
WooCommerce Webhook Verification Utilities

WooCommerce sends webhook payloads with an HMAC-SHA256 signature
in the X-WC-Webhook-Signature header for verification.
"""
import hmac
import hashlib
import base64
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def verify_woocommerce_webhook(
    payload: bytes,
    signature: str,
    secret: str
) -> bool:
    """
    Verify WooCommerce webhook HMAC signature.

    WooCommerce sends the signature in the X-WC-Webhook-Signature header.
    The signature is: base64(HMAC-SHA256(payload, secret))

    Args:
        payload: Raw request body bytes
        signature: Value from X-WC-Webhook-Signature header
        secret: Webhook secret configured when creating the webhook

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not secret:
        logger.warning("Missing signature or secret for webhook verification")
        return False

    try:
        # Calculate expected signature
        expected_signature = base64.b64encode(
            hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).digest()
        ).decode('utf-8')

        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(expected_signature, signature)

        if not is_valid:
            logger.warning("Webhook signature verification failed")

        return is_valid

    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False


def generate_webhook_secret(length: int = 32) -> str:
    """
    Generate a secure random secret for webhook signing.

    Args:
        length: Length of the secret in bytes (will be URL-safe base64 encoded)

    Returns:
        URL-safe base64 encoded random string
    """
    import secrets
    return secrets.token_urlsafe(length)


class WebhookHeaders:
    """
    Parser for WooCommerce webhook headers.

    WooCommerce webhook headers:
    - X-WC-Webhook-Source: Store URL (e.g., https://mystore.com/)
    - X-WC-Webhook-Topic: Event topic (e.g., product.created)
    - X-WC-Webhook-Resource: Resource type (e.g., product)
    - X-WC-Webhook-Event: Event action (e.g., created)
    - X-WC-Webhook-Signature: Base64 HMAC-SHA256 signature
    - X-WC-Webhook-ID: Webhook subscription ID
    - X-WC-Webhook-Delivery-ID: Unique delivery ID for this event
    """

    def __init__(
        self,
        source: Optional[str] = None,
        topic: Optional[str] = None,
        resource: Optional[str] = None,
        event: Optional[str] = None,
        signature: Optional[str] = None,
        webhook_id: Optional[str] = None,
        delivery_id: Optional[str] = None
    ):
        self.source = source
        self.topic = topic
        self.resource = resource
        self.event = event
        self.signature = signature
        self.webhook_id = webhook_id
        self.delivery_id = delivery_id

    @classmethod
    def from_request_headers(cls, headers: dict) -> "WebhookHeaders":
        """
        Parse webhook headers from request headers dict.

        Args:
            headers: Request headers dictionary

        Returns:
            WebhookHeaders instance
        """
        # Headers are case-insensitive, so normalize to lowercase
        normalized = {k.lower(): v for k, v in headers.items()}

        return cls(
            source=normalized.get('x-wc-webhook-source'),
            topic=normalized.get('x-wc-webhook-topic'),
            resource=normalized.get('x-wc-webhook-resource'),
            event=normalized.get('x-wc-webhook-event'),
            signature=normalized.get('x-wc-webhook-signature'),
            webhook_id=normalized.get('x-wc-webhook-id'),
            delivery_id=normalized.get('x-wc-webhook-delivery-id')
        )

    def get_store_url(self) -> Optional[str]:
        """Get normalized store URL (without trailing slash)"""
        if self.source:
            return self.source.rstrip('/')
        return None

    def is_valid(self) -> bool:
        """Check if essential headers are present"""
        return bool(self.source and self.topic and self.signature)
