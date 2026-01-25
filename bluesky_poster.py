"""Post to Bluesky with image and link support."""

import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from atproto import Client, models

from post_generator import BlueskyPost
from figure_extractor import ExtractedFigure


class BlueskyPoster:
    """Handle posting to Bluesky with images and links."""

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        """Initialize the Bluesky client.

        Args:
            username: Bluesky username/handle (defaults to BLUESKY_USERNAME env var)
            password: Bluesky password or app password (defaults to BLUESKY_PASSWORD env var)
        """
        self.username = username or os.environ.get("BLUESKY_USERNAME")
        self.password = password or os.environ.get("BLUESKY_PASSWORD")

        if not self.username or not self.password:
            raise ValueError(
                "Bluesky credentials required. Set BLUESKY_USERNAME and BLUESKY_PASSWORD "
                "environment variables or pass them directly."
            )

        self.client = Client()
        self._logged_in = False

    def login(self) -> bool:
        """Authenticate with Bluesky.

        Returns:
            True if login successful
        """
        try:
            self.client.login(self.username, self.password)
            self._logged_in = True
            print(f"Logged in to Bluesky as {self.username}")
            return True
        except Exception as e:
            print(f"Failed to login to Bluesky: {e}")
            return False

    def _upload_image(self, image_bytes: bytes, alt_text: str = "") -> Optional[models.AppBskyEmbedImages.Image]:
        """Upload an image to Bluesky.

        Args:
            image_bytes: Image data as bytes
            alt_text: Alt text description for accessibility

        Returns:
            Image model for embedding, or None if upload fails
        """
        try:
            upload = self.client.upload_blob(image_bytes)
            return models.AppBskyEmbedImages.Image(
                alt=alt_text or "Figure from preprint",
                image=upload.blob
            )
        except Exception as e:
            print(f"Failed to upload image: {e}")
            return None

    def _create_facets_for_link(self, text: str, url: str) -> tuple[str, List[models.AppBskyRichtextFacet.Main]]:
        """Create facets for a link in the post text.

        Returns the text with the URL appended and the facets for rich text.
        """
        # Append the URL to the text
        full_text = f"{text}\n\n{url}"

        # Calculate byte positions for the URL
        text_bytes = full_text.encode("utf-8")
        url_bytes = url.encode("utf-8")
        url_start = len(full_text.encode("utf-8")) - len(url_bytes)
        url_end = len(text_bytes)

        facet = models.AppBskyRichtextFacet.Main(
            index=models.AppBskyRichtextFacet.ByteSlice(
                byte_start=url_start,
                byte_end=url_end
            ),
            features=[
                models.AppBskyRichtextFacet.Link(uri=url)
            ]
        )

        return full_text, [facet]

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        """Parse an AT URI into (did, rkey).

        Args:
            uri: AT URI like 'at://did:plc:xxx/app.bsky.feed.post/yyy'

        Returns:
            Tuple of (did, rkey)
        """
        # Format: at://did:plc:xxx/app.bsky.feed.post/rkey
        parts = uri.replace("at://", "").split("/")
        did = parts[0]
        rkey = parts[-1]
        return did, rkey

    def _get_post_ref(self, uri: str) -> models.ComAtprotoRepoStrongRef.Main:
        """Get a strong reference for an existing post by URI.

        Args:
            uri: AT URI of the post

        Returns:
            Strong reference to the post
        """
        did, rkey = self._parse_uri(uri)

        # Fetch the post to get its CID
        response = self.client.get_post(rkey, did)

        return models.ComAtprotoRepoStrongRef.Main(
            uri=uri,
            cid=response.cid
        )

    def post_reply(
        self,
        text: str,
        reply_to_uri: str,
        root_uri: Optional[str] = None
    ) -> Optional[str]:
        """Post a reply to an existing post.

        Args:
            text: Reply text
            reply_to_uri: AT URI of the post to reply to
            root_uri: AT URI of the thread root (defaults to reply_to_uri)

        Returns:
            Post URI if successful, None otherwise
        """
        if not self._logged_in:
            if not self.login():
                return None

        try:
            # Get references for parent and root
            parent_ref = self._get_post_ref(reply_to_uri)
            root_ref = self._get_post_ref(root_uri) if root_uri else parent_ref

            reply = models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=root_ref
            )

            response = self.client.send_post(
                text=text,
                reply_to=reply
            )

            print(f"Posted reply successfully: {response.uri}")
            return response.uri

        except Exception as e:
            print(f"Failed to post reply: {e}")
            return None

    def post_single(
        self,
        text: str,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint"
    ) -> Optional[str]:
        """Post a single post to Bluesky.

        Args:
            text: Post text
            link_url: Optional URL to include as a link
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            Post URI if successful, None otherwise
        """
        if not self._logged_in:
            if not self.login():
                return None

        try:
            # Prepare text and facets
            facets = None
            if link_url:
                text, facets = self._create_facets_for_link(text, link_url)

            # Prepare image embed
            embed = None
            if image:
                img = self._upload_image(image.image_bytes, image_alt)
                if img:
                    embed = models.AppBskyEmbedImages.Main(images=[img])

            # Create the post
            response = self.client.send_post(
                text=text,
                facets=facets,
                embed=embed
            )

            print(f"Posted successfully: {response.uri}")
            return response.uri

        except Exception as e:
            print(f"Failed to post: {e}")
            return None

    def post_thread(
        self,
        posts: List[str],
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint"
    ) -> Optional[List[str]]:
        """Post a thread to Bluesky.

        Args:
            posts: List of post texts (in order)
            link_url: URL to include in the first post
            image: Optional figure to attach to the first post
            image_alt: Alt text for the image

        Returns:
            List of post URIs if successful, None otherwise
        """
        if not self._logged_in:
            if not self.login():
                return None

        if not posts:
            print("No posts to publish")
            return None

        try:
            uris = []
            parent_ref = None
            root_ref = None

            for i, post_text in enumerate(posts):
                # First post gets the link and image
                facets = None
                embed = None

                if i == 0:
                    if link_url:
                        post_text, facets = self._create_facets_for_link(post_text, link_url)
                    if image:
                        img = self._upload_image(image.image_bytes, image_alt)
                        if img:
                            embed = models.AppBskyEmbedImages.Main(images=[img])

                # Build reply reference for thread
                reply = None
                if parent_ref and root_ref:
                    reply = models.AppBskyFeedPost.ReplyRef(
                        parent=parent_ref,
                        root=root_ref
                    )

                # Create the post
                response = self.client.send_post(
                    text=post_text,
                    facets=facets,
                    embed=embed,
                    reply_to=reply
                )

                uris.append(response.uri)
                print(f"Posted thread part {i+1}: {response.uri}")

                # Update references for next post
                parent_ref = models.create_strong_ref(response)
                if root_ref is None:
                    root_ref = parent_ref

            return uris

        except Exception as e:
            print(f"Failed to post thread: {e}")
            return None

    def post(
        self,
        bluesky_post: BlueskyPost,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint"
    ) -> Optional[List[str]]:
        """Post a BlueskyPost object (single or thread).

        Args:
            bluesky_post: The BlueskyPost object to publish
            link_url: URL to include
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            List of post URIs if successful, None otherwise
        """
        if bluesky_post.is_thread:
            return self.post_thread(
                bluesky_post.posts,
                link_url=link_url,
                image=image,
                image_alt=image_alt
            )
        else:
            uri = self.post_single(
                bluesky_post.posts[0],
                link_url=link_url,
                image=image,
                image_alt=image_alt
            )
            return [uri] if uri else None


if __name__ == "__main__":
    # Test posting (dry run - won't actually post without credentials)
    print("BlueskyPoster module loaded successfully")
    print("To test, ensure BLUESKY_USERNAME and BLUESKY_PASSWORD are set")
