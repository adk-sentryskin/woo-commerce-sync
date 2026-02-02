"""
WooCommerce REST API Client

Handles all communication with WooCommerce stores via their REST API.
Uses Basic Auth over HTTPS (recommended) or OAuth 1.0a over HTTP.
"""
import httpx
from typing import Optional, List, Dict, Any
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class WooCommerceClient:
    """
    REST API client for WooCommerce stores.

    WooCommerce REST API uses:
    - Basic Auth over HTTPS (recommended)
    - OAuth 1.0a over HTTP (for non-SSL sites)

    API Documentation: https://woocommerce.github.io/woocommerce-rest-api-docs/
    """

    def __init__(
        self,
        store_url: str,
        consumer_key: str,
        consumer_secret: str,
        api_version: str = "wc/v3"
    ):
        """
        Initialize WooCommerce client.

        Args:
            store_url: Full store URL (e.g., https://mystore.com)
            consumer_key: WooCommerce REST API Consumer Key (ck_xxx)
            consumer_secret: WooCommerce REST API Consumer Secret (cs_xxx)
            api_version: API version (default: wc/v3)
        """
        self.store_url = store_url.rstrip('/')
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.api_version = api_version
        self.base_url = f"{self.store_url}/wp-json/{api_version}"
        self.is_ssl = store_url.startswith("https://")
        self.timeout = settings.WC_REQUEST_TIMEOUT

    def _get_auth(self) -> httpx.BasicAuth:
        """
        Return authentication method.

        For HTTPS: Use Basic Auth (recommended)
        For HTTP: Would use OAuth 1.0a (not implemented - HTTPS required)
        """
        if not self.is_ssl:
            logger.warning(f"Store {self.store_url} is not using HTTPS. Basic Auth may not work.")

        return httpx.BasicAuth(self.consumer_key, self.consumer_secret)

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to WooCommerce API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., /products)
            params: Query parameters
            data: Request body for POST/PUT

        Returns:
            Response JSON data
        """
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    auth=self._get_auth(),
                    params=params,
                    json=data
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"WooCommerce API error: {e.response.status_code} - {e.response.text}")
                raise
            except httpx.RequestError as e:
                logger.error(f"WooCommerce request error: {e}")
                raise

    async def _make_request_with_headers(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        """
        Make request and return both response data and headers.
        Useful for pagination (X-WP-Total, X-WP-TotalPages headers).
        """
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                auth=self._get_auth(),
                params=params,
                json=data
            )
            response.raise_for_status()
            return response.json(), dict(response.headers)

    # ========================================================================
    # System Endpoints
    # ========================================================================

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Get WooCommerce system status.
        Useful for verifying connection and getting store info.

        Returns:
            System status including WC version, WP version, etc.
        """
        return await self._make_request("GET", "/system_status")

    async def verify_connection(self) -> Dict[str, Any]:
        """
        Verify API credentials by fetching system status.

        Returns:
            Dict with connection status and store info
        """
        try:
            status = await self.get_system_status()

            # Extract version info from environment
            environment = status.get('environment', {})

            return {
                "connected": True,
                "wp_version": environment.get('wp_version'),
                "wc_version": environment.get('version'),
                "php_version": environment.get('php_version'),
                "site_url": environment.get('site_url'),
                "home_url": environment.get('home_url'),
                "store_id": status.get('store_id'),
            }
        except Exception as e:
            logger.error(f"Connection verification failed: {e}")
            return {
                "connected": False,
                "error": str(e)
            }

    # ========================================================================
    # Product Endpoints
    # ========================================================================

    async def get_products(
        self,
        page: int = 1,
        per_page: int = 100,
        status: str = "any",
        orderby: str = "id",
        order: str = "asc"
    ) -> tuple[List[Dict[str, Any]], int, int]:
        """
        Fetch products with pagination.

        Args:
            page: Page number (1-indexed)
            per_page: Products per page (max 100)
            status: Filter by status (any, publish, draft, pending, private)
            orderby: Sort by field (id, date, title, etc.)
            order: Sort order (asc, desc)

        Returns:
            Tuple of (products list, total count, total pages)
        """
        params = {
            'page': page,
            'per_page': min(per_page, 100),  # WooCommerce max is 100
            'status': status,
            'orderby': orderby,
            'order': order
        }

        data, headers = await self._make_request_with_headers("GET", "/products", params=params)

        total = int(headers.get('X-WP-Total', 0))
        total_pages = int(headers.get('X-WP-TotalPages', 0))

        return data, total, total_pages

    async def get_product(self, product_id: int) -> Dict[str, Any]:
        """
        Fetch a single product by ID.

        Args:
            product_id: WooCommerce product ID

        Returns:
            Product data
        """
        return await self._make_request("GET", f"/products/{product_id}")

    async def get_product_variations(
        self,
        product_id: int,
        page: int = 1,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch variations for a variable product.

        Args:
            product_id: Parent product ID
            page: Page number
            per_page: Items per page

        Returns:
            List of variations
        """
        params = {
            'page': page,
            'per_page': per_page
        }
        return await self._make_request("GET", f"/products/{product_id}/variations", params=params)

    async def get_products_count(self, status: str = "any") -> int:
        """
        Get total count of products.

        Args:
            status: Filter by status

        Returns:
            Total product count
        """
        _, total, _ = await self.get_products(page=1, per_page=1, status=status)
        return total

    # ========================================================================
    # Category Endpoints
    # ========================================================================

    async def get_categories(
        self,
        page: int = 1,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch product categories"""
        params = {
            'page': page,
            'per_page': per_page
        }
        return await self._make_request("GET", "/products/categories", params=params)

    # ========================================================================
    # Webhook Endpoints
    # ========================================================================

    async def create_webhook(
        self,
        topic: str,
        delivery_url: str,
        secret: str,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a webhook in WooCommerce.

        Args:
            topic: Webhook topic (e.g., product.created, product.updated)
            delivery_url: URL to receive webhook payloads
            secret: Secret for HMAC signature verification
            name: Display name for the webhook

        Returns:
            Created webhook data
        """
        payload = {
            "name": name or f"CheckoutAI - {topic}",
            "topic": topic,
            "delivery_url": delivery_url,
            "secret": secret,
            "status": "active"
        }

        return await self._make_request("POST", "/webhooks", data=payload)

    async def get_webhooks(
        self,
        page: int = 1,
        per_page: int = 100,
        status: str = "active"
    ) -> List[Dict[str, Any]]:
        """
        List all webhooks.

        Args:
            page: Page number
            per_page: Items per page
            status: Filter by status (active, paused, disabled)

        Returns:
            List of webhooks
        """
        params = {
            'page': page,
            'per_page': per_page,
            'status': status
        }
        return await self._make_request("GET", "/webhooks", params=params)

    async def get_webhook(self, webhook_id: int) -> Dict[str, Any]:
        """Get a single webhook by ID"""
        return await self._make_request("GET", f"/webhooks/{webhook_id}")

    async def update_webhook(
        self,
        webhook_id: int,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a webhook.

        Args:
            webhook_id: Webhook ID to update
            data: Fields to update

        Returns:
            Updated webhook data
        """
        return await self._make_request("PUT", f"/webhooks/{webhook_id}", data=data)

    async def delete_webhook(self, webhook_id: int, force: bool = True) -> Dict[str, Any]:
        """
        Delete a webhook.

        Args:
            webhook_id: Webhook ID to delete
            force: Force delete (required to actually delete)

        Returns:
            Deleted webhook data
        """
        params = {'force': force}
        return await self._make_request("DELETE", f"/webhooks/{webhook_id}", params=params)

    # ========================================================================
    # Order Endpoints (for future use)
    # ========================================================================

    async def get_orders(
        self,
        page: int = 1,
        per_page: int = 100,
        status: str = "any"
    ) -> List[Dict[str, Any]]:
        """Fetch orders (for future analytics)"""
        params = {
            'page': page,
            'per_page': per_page,
            'status': status
        }
        return await self._make_request("GET", "/orders", params=params)
