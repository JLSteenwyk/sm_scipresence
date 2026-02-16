"""Post to LinkedIn with image support.

Uses the LinkedIn Posts API with OAuth2 authentication.
LinkedIn does not support threading, so thread posts are joined into a single post.
"""

import os
from pathlib import Path
from typing import List, Optional

import requests

from post_generator import BlueskyPost
from figure_extractor import ExtractedFigure

# LinkedIn API version in YYYYMM format
LINKEDIN_API_VERSION = "202601"


class LinkedInPoster:
    """Handle posting to LinkedIn with images."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("LINKEDIN_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("LINKEDIN_CLIENT_SECRET")
        self.access_token = access_token or os.environ.get("LINKEDIN_ACCESS_TOKEN")
        self.refresh_token = refresh_token or os.environ.get("LINKEDIN_REFRESH_TOKEN")

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "LinkedIn credentials required. Set LINKEDIN_CLIENT_ID and "
                "LINKEDIN_CLIENT_SECRET in .env"
            )

        if not self.access_token:
            raise ValueError(
                "LinkedIn access token required. Set LINKEDIN_ACCESS_TOKEN in .env "
                "(run the cross_poster OAuth flow first to obtain tokens)"
            )

        self._person_id = None
        print("LinkedIn client initialized")

    def _api_headers(self) -> dict:
        """Return standard headers for LinkedIn REST API calls."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": LINKEDIN_API_VERSION,
        }

    def _get_person_id(self) -> str:
        """Fetch the authenticated user's person ID."""
        if self._person_id:
            return self._person_id

        resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        resp.raise_for_status()
        self._person_id = resp.json()["sub"]
        return self._person_id

    def _refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            return False

        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )

        if resp.status_code != 200:
            return False

        tokens = resp.json()
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens.get("refresh_token", self.refresh_token)
        self._save_tokens()
        return True

    def _save_tokens(self):
        """Save access and refresh tokens back to .env file."""
        env_path = Path(__file__).parent / ".env"
        if not env_path.exists():
            return

        content = env_path.read_text()
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            if line.startswith("LINKEDIN_ACCESS_TOKEN="):
                new_lines.append(f"LINKEDIN_ACCESS_TOKEN={self.access_token}")
            elif line.startswith("LINKEDIN_REFRESH_TOKEN="):
                new_lines.append(f"LINKEDIN_REFRESH_TOKEN={self.refresh_token}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines))

    def _upload_image(self, image_bytes: bytes) -> Optional[str]:
        """Upload an image to LinkedIn using the Images API.

        Returns image URN (urn:li:image:...) or None.
        """
        try:
            person_id = self._get_person_id()

            # Step 1: Initialize upload
            init_resp = requests.post(
                "https://api.linkedin.com/rest/images?action=initializeUpload",
                headers=self._api_headers(),
                json={
                    "initializeUploadRequest": {
                        "owner": f"urn:li:person:{person_id}",
                    }
                },
            )
            init_resp.raise_for_status()

            upload_data = init_resp.json()["value"]
            upload_url = upload_data["uploadUrl"]
            image_urn = upload_data["image"]

            # Step 2: Upload the binary image
            requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                data=image_bytes,
            )

            return image_urn

        except Exception as e:
            print(f"Failed to upload image to LinkedIn: {e}")
            return None

    def post_single(
        self,
        text: str,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> bool:
        """Post a single post to LinkedIn.

        Args:
            text: Post text
            link_url: Optional URL to append
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            True if successful, False otherwise
        """
        full_text = f"{text}\n\n{link_url}" if link_url else text

        try:
            person_id = self._get_person_id()

            payload = {
                "author": f"urn:li:person:{person_id}",
                "commentary": full_text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            if image:
                image_urn = self._upload_image(image.image_bytes)
                if image_urn:
                    payload["content"] = {
                        "media": {
                            "id": image_urn,
                        }
                    }

            resp = requests.post(
                "https://api.linkedin.com/rest/posts",
                headers=self._api_headers(),
                json=payload,
            )

            if resp.status_code == 201:
                print("Posted to LinkedIn successfully")
                return True

            # Try token refresh on 401
            if resp.status_code == 401 and self._refresh_access_token():
                print("Refreshed LinkedIn token, retrying...")
                resp = requests.post(
                    "https://api.linkedin.com/rest/posts",
                    headers=self._api_headers(),
                    json=payload,
                )
                if resp.status_code == 201:
                    print("Posted to LinkedIn successfully (after token refresh)")
                    return True

            print(f"LinkedIn post failed (status {resp.status_code}): {resp.text}")
            return False

        except Exception as e:
            print(f"Failed to post to LinkedIn: {e}")
            return False

    def post_thread(
        self,
        posts: List[str],
        link_url: Optional[str] = None,
        link_urls: Optional[List[Optional[str]]] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> bool:
        """Post a thread to LinkedIn (joined into a single post).

        LinkedIn does not support threading, so all posts are joined with
        paragraph breaks into one post.

        Args:
            posts: List of post texts (in order)
            link_url: URL to include
            link_urls: Per-post URLs (first non-None is used)
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            True if successful, False otherwise
        """
        if not posts:
            print("No posts to publish to LinkedIn")
            return False

        # Join all parts into a single post
        full_text = "\n\n".join(posts)

        # Determine which URL to use
        url = link_url
        if link_urls:
            for u in link_urls:
                if u:
                    url = u
                    break

        return self.post_single(full_text, link_url=url, image=image, image_alt=image_alt)

    def post(
        self,
        bluesky_post: BlueskyPost,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> bool:
        """Post a BlueskyPost object to LinkedIn.

        Args:
            bluesky_post: The BlueskyPost object to publish
            link_url: URL to include
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            True if successful, False otherwise
        """
        if bluesky_post.is_thread:
            return self.post_thread(
                bluesky_post.posts,
                link_url=link_url,
                image=image,
                image_alt=image_alt,
            )
        else:
            return self.post_single(
                bluesky_post.posts[0],
                link_url=link_url,
                image=image,
                image_alt=image_alt,
            )


if __name__ == "__main__":
    print("LinkedInPoster module loaded successfully")
    print("To test, ensure LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,")
    print("and LINKEDIN_ACCESS_TOKEN are set")
