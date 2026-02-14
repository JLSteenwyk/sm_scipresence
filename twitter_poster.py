"""Post to Twitter/X with image and thread support."""

import os
import tempfile
from typing import List, Optional

import tweepy

from post_generator import BlueskyPost
from figure_extractor import ExtractedFigure


class TwitterPoster:
    """Handle posting to Twitter/X with images and threads."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("TWITTER_API_KEY")
        self.api_secret = api_secret or os.environ.get("TWITTER_API_SECRET")
        self.access_token = access_token or os.environ.get("TWITTER_ACCESS_TOKEN")
        self.access_token_secret = access_token_secret or os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

        if not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            raise ValueError(
                "Twitter credentials required. Set TWITTER_API_KEY, TWITTER_API_SECRET, "
                "TWITTER_ACCESS_TOKEN, and TWITTER_ACCESS_TOKEN_SECRET environment variables "
                "or pass them directly."
            )

        # v2 client for posting tweets
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
        )

        # v1.1 API for media uploads (v2 doesn't support media upload yet)
        auth = tweepy.OAuth1UserHandler(
            self.api_key, self.api_secret,
            self.access_token, self.access_token_secret,
        )
        self.api_v1 = tweepy.API(auth)

        print("Twitter client initialized")

    def _upload_image(self, image_bytes: bytes, alt_text: str = "") -> Optional[int]:
        """Upload an image to Twitter.

        Args:
            image_bytes: Image data as bytes
            alt_text: Alt text description for accessibility

        Returns:
            Media ID if successful, None otherwise
        """
        try:
            # Write image to a temp file (tweepy v1.1 requires a file path)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            media = self.api_v1.media_upload(filename=tmp_path)

            if alt_text:
                self.api_v1.create_media_metadata(media.media_id, alt_text[:1000])

            # Clean up temp file
            os.unlink(tmp_path)

            return media.media_id
        except Exception as e:
            print(f"Failed to upload image to Twitter: {e}")
            return None

    def post_single(
        self,
        text: str,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> Optional[int]:
        """Post a single tweet.

        Args:
            text: Tweet text
            link_url: Optional URL to append
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            Tweet ID if successful, None otherwise
        """
        try:
            # Append link URL to text (Twitter auto-shortens URLs to 23 chars)
            full_text = f"{text}\n\n{link_url}" if link_url else text

            # Upload image if provided
            media_ids = None
            if image:
                media_id = self._upload_image(image.image_bytes, image_alt)
                if media_id:
                    media_ids = [media_id]

            response = self.client.create_tweet(
                text=full_text,
                media_ids=media_ids,
            )

            tweet_id = response.data["id"]
            print(f"Tweeted successfully: {tweet_id}")
            return tweet_id

        except Exception as e:
            print(f"Failed to tweet: {e}")
            return None

    def post_thread(
        self,
        posts: List[str],
        link_url: Optional[str] = None,
        link_urls: Optional[List[Optional[str]]] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> Optional[List[int]]:
        """Post a thread to Twitter.

        Args:
            posts: List of tweet texts (in order)
            link_url: URL to include in the first tweet
            link_urls: Per-tweet URLs (same length as posts). Overrides link_url if provided.
            image: Optional figure to attach to the first tweet
            image_alt: Alt text for the image

        Returns:
            List of tweet IDs if successful, None otherwise
        """
        if not posts:
            print("No posts to publish")
            return None

        try:
            tweet_ids = []
            previous_tweet_id = None

            for i, post_text in enumerate(posts):
                media_ids = None

                # Determine link for this tweet
                post_link = None
                if link_urls and i < len(link_urls):
                    post_link = link_urls[i]
                elif i == 0 and link_url:
                    post_link = link_url

                if post_link:
                    post_text = f"{post_text}\n\n{post_link}"

                # Upload image for first tweet only
                if i == 0 and image:
                    media_id = self._upload_image(image.image_bytes, image_alt)
                    if media_id:
                        media_ids = [media_id]

                # Reply to previous tweet to form thread
                response = self.client.create_tweet(
                    text=post_text,
                    media_ids=media_ids,
                    in_reply_to_tweet_id=previous_tweet_id,
                )

                tweet_id = response.data["id"]
                tweet_ids.append(tweet_id)
                previous_tweet_id = tweet_id
                print(f"Tweeted thread part {i+1}: {tweet_id}")

            return tweet_ids

        except Exception as e:
            print(f"Failed to post thread to Twitter: {e}")
            return None

    def post_reply(
        self,
        text: str,
        reply_to_tweet_id: int,
    ) -> Optional[int]:
        """Post a reply to an existing tweet.

        Args:
            text: Reply text
            reply_to_tweet_id: ID of the tweet to reply to

        Returns:
            Tweet ID if successful, None otherwise
        """
        try:
            response = self.client.create_tweet(
                text=text,
                in_reply_to_tweet_id=reply_to_tweet_id,
            )

            tweet_id = response.data["id"]
            print(f"Posted reply on Twitter: {tweet_id}")
            return tweet_id

        except Exception as e:
            print(f"Failed to post reply on Twitter: {e}")
            return None

    def post(
        self,
        bluesky_post: BlueskyPost,
        link_url: Optional[str] = None,
        image: Optional[ExtractedFigure] = None,
        image_alt: str = "Figure from preprint",
    ) -> Optional[List[int]]:
        """Post a BlueskyPost object (single or thread) to Twitter.

        Args:
            bluesky_post: The BlueskyPost object to publish
            link_url: URL to include
            image: Optional figure to attach
            image_alt: Alt text for the image

        Returns:
            List of tweet IDs if successful, None otherwise
        """
        if bluesky_post.is_thread:
            return self.post_thread(
                bluesky_post.posts,
                link_url=link_url,
                image=image,
                image_alt=image_alt,
            )
        else:
            tweet_id = self.post_single(
                bluesky_post.posts[0],
                link_url=link_url,
                image=image,
                image_alt=image_alt,
            )
            return [tweet_id] if tweet_id else None


if __name__ == "__main__":
    print("TwitterPoster module loaded successfully")
    print("To test, ensure TWITTER_API_KEY, TWITTER_API_SECRET,")
    print("TWITTER_ACCESS_TOKEN, and TWITTER_ACCESS_TOKEN_SECRET are set")
