from datetime import date, datetime
from pyncm import apis
from tqdm import tqdm
from unidecode import unidecode
import base64
import re
import spotipy
from spotipy.exceptions import SpotifyException
import sys
import yaml
from loguru import logger
import logger as log_setup
import json
import os
import requests

DEFAULT_COVER_PATH = "assets/netease.png"
SPOTIFY_SCOPES = "playlist-modify-public playlist-modify-private user-library-read ugc-image-upload"
TOKEN_CACHE_FILE = ".spotify_token.json"

# For some reason, Netease's API sometimes returns a publishTime of really weird unix timestamp like year 2240 after converting to time
# so we need to filter out those strange values
# This will not affect songs published before unix start, just that in Spotify's search query, will not use the year filter
# in ms
UNIX_START = 1000
MS_PER_S = 1000
NEXT_YEAR = datetime(datetime.now().year + 1, 1, 1).timestamp() * MS_PER_S

class NeteaseToSpotify:
    def __init__(self):
        logger.info("---------- Starting Application ----------")
        
        with open("config.yml", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            try:
                # Set up cache handler for token
                cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), TOKEN_CACHE_FILE)
                
                if os.path.exists(cache_path):
                    logger.info("Using cached token for authentication")
                    try:
                        auth_manager = spotipy.oauth2.SpotifyOAuth(
                            client_id=config["client_id"],
                            client_secret=config["client_secret"],
                            redirect_uri="http://localhost:8888/callback",  # Default redirect URI
                            scope=SPOTIFY_SCOPES,
                            cache_path=cache_path,
                            open_browser=False
                        )
                        
                        # Try to get a valid token (this will refresh if expired)
                        token_info = auth_manager.get_cached_token()
                        if not token_info:
                            raise SpotifyException("Cached token is invalid or expired")
                            
                    except SpotifyException as e:
                        logger.warning("Cached token is invalid or expired. Removing cache and requesting new authentication.")
                        os.remove(cache_path)
                        auth_manager = self._create_new_auth_manager(config)
                        
                else:
                    logger.info("No cached token found. Please authenticate in browser (one-time setup)")
                    auth_manager = self._create_new_auth_manager(config)
                
                self.spotify = spotipy.Spotify(auth_manager=auth_manager)
                # Verify the connection and get user info
                user_info = self.spotify.me()
                logger.info(f"Successfully authenticated as {user_info['display_name']}")
                logger.debug("Token will be automatically refreshed when needed (valid for 1 hour, refresh token valid indefinitely)")
                
            except SpotifyException as e:
                logger.error(f"Spotify authorization failed: {str(e)}")
                logger.error("If this persists, please check:")
                logger.error("1. Your client_id and client_secret are correct")
                logger.error("2. The app still exists in your Spotify account")
                logger.error("3. You haven't revoked access for this app")
                sys.exit(1)
            except Exception as e:
                logger.error(f"Unexpected error during authorization: {str(e)}")
                sys.exit(1)
                
            # Use netease.png as default Spotify playlist cover image
            self.cover_image_path = config["cover_image_path"] if config["cover_image_path"] != "DESIRED_SPOTIFY_PLAYLIST_COVER_IMAGE_PATH" else DEFAULT_COVER_PATH
            self.netease_playlists = config["netease_playlists"]
            self.playlist_prefix = config.get("playlist_prefix", "")  # Get prefix with empty string as default
    
    def _create_new_auth_manager(self, config):
        """Create a new auth manager for initial authentication"""
        return spotipy.oauth2.SpotifyOAuth(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            redirect_uri="http://localhost:8888/callback",  # Default redirect URI
            scope=SPOTIFY_SCOPES,
            cache_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), TOKEN_CACHE_FILE)
        )
    
    def migrate(self):
        """
        Migrate multiple Netease playlists to Spotify

        :return: None
        """
        logger.info(f"Starting migration of {len(self.netease_playlists)} playlists...")
        
        for playlist in self.netease_playlists:
            playlist_id = playlist["id"]
            limit = playlist.get("limit", 0)  # 0 or None means no limit
            logger.info(f"Migrating playlist with ID: {playlist_id} (limit: {'unlimited' if not limit else limit} songs)")
            self._migrate_single_playlist(playlist_id, limit)
            
    def _migrate_single_playlist(self, playlist_id, limit=0):
        """
        Migrate a single Netease playlist to Spotify

        :param playlist_id: The ID of the Netease playlist to migrate
        :param limit: Maximum number of songs to migrate (0 for no limit)
        :return: None
        """
        try:
            # Get playlist info to use its name
            playlist_info = apis.playlist.GetPlaylistInfo(playlist_id)
            playlist_name = playlist_info["playlist"]["name"]
            
            # Add prefix to playlist name
            spotify_playlist_name = f"{self.playlist_prefix}{playlist_name}"
            
            logger.info(f"Creating/updating Spotify playlist: {spotify_playlist_name}")
            spotify_playlist_id = self.get_or_create_playlist(spotify_playlist_name, coverImgUrl=playlist_info["playlist"]["coverImgUrl"])
            
            # Get existing tracks in the Spotify playlist to avoid duplicates
            existing_tracks = self.get_playlist_tracks(spotify_playlist_id)
            logger.debug(f"Found {len(existing_tracks)} existing tracks in playlist")
            
            # Get tracks from Netease playlist
            netease_playlist_tracks_name_and_artist = self.get_netease_playlist_tracks_name_and_artist(playlist_info, limit)
            
            logger.info(f"---------- Inserting Songs to Spotify Playlist: {spotify_playlist_name} ----------")
            for name, artist, year in tqdm(netease_playlist_tracks_name_and_artist):
                # Delete all parentheses because whatever inside will make search return much less/no results
                trimmed_name = re.sub(r'\(.*\)', '', name)
                try:
                    track_id = self.search_for_track(year, trimmed_name, artist)
                    # Only add if not already in playlist
                    if track_id not in existing_tracks:
                        logger.debug(f"Adding track: {name} - {artist}")
                        self.spotify.playlist_add_items(spotify_playlist_id, [track_id], 0)
                    else:
                        logger.debug(f"Skipping duplicate track: {name} - {artist}")
                except Exception as e:
                    logger.warning(f"Spotify does not have this song's copyright: {unidecode(name)}, {unidecode(artist)}")
        except Exception as e:
            logger.error(f"Failed to migrate playlist {playlist_id}: {str(e)}")
    
    def get_or_create_playlist(self, playlist_name, coverImgUrl=None):
        """
        Get or create the playlist with the given name

        :param playlist_name: Name of the playlist to get or create
        :return: the playlist's Spotify ID
        :rtype: str
        """
        playlist_id = None
        try:
            # First search through all current user's playlists to see if a playlist with the same name already exists
            user_playlists = self.spotify.user_playlists(self.spotify.me()["id"])
            for playlist in user_playlists["items"]:
                if playlist["name"] == playlist_name:
                    playlist_id = playlist["id"]
                    logger.debug(f"Found existing playlist: {playlist_name}")
                    break
            if not playlist_id:
                logger.info("Creating new playlist")
                playlist_id = self.create_playlist(playlist_name, coverImgUrl)
            else:
                if coverImgUrl:
                    logger.debug("Updating playlist cover image")
                    try:
                        b64_cover_image = self.get_base64_from_url(coverImgUrl)
                        if b64_cover_image:
                            self.spotify.playlist_upload_cover_image(playlist_id, b64_cover_image)
                        logger.debug("Uploaded playlist cover image")
                    except Exception as e:
                        logger.error(f"Failed to update playlist cover image: {str(e)}")
                else:
                    logger.debug("No cover image to update")
        except Exception as e:
            logger.error(f"Failed to get or create playlist {playlist_name}: {str(e)}")
            raise
        return playlist_id

    def create_playlist(self, playlist_name, coverImgUrl=None):
        """
        Create a playlist

        :param playlist_name: Name of the playlist to create
        :return: the new playlist's Spotify ID
        :rtype: str
        """
        try:
            playlist_id = self.spotify.user_playlist_create(self.spotify.me()["id"], playlist_name)["id"]
            logger.info(f"Created new playlist: {playlist_name}")
            
            try:
                if coverImgUrl:
                    b64_cover_image = self.get_base64_from_url(coverImgUrl)
                    if not b64_cover_image:
                        b64_cover_image = self.get_base64_from_image(self.cover_image_path)
                else:
                    b64_cover_image = self.get_base64_from_image(self.cover_image_path)
                self.spotify.playlist_upload_cover_image(playlist_id, b64_cover_image)
                logger.debug("Uploaded playlist cover image")
            except Exception as e:
                logger.error(f"Failed to upload cover image: {str(e)}")
                raise
                
            return playlist_id
        except Exception as e:
            logger.error(f"Failed to create playlist {playlist_name}: {str(e)}")
            raise

    def get_netease_playlist_tracks_name_and_artist(self, playlist, limit=0):
        """
        Get tracks' name and 1st artist in the given Netease playlist

        :param playlist: Netease playlist
        :param limit: Maximum number of songs to return (0 for no limit)
        :return: list of (name, artist) pairs of tracks in the playlist, in reverse order
        :rtype: list(tuple(str, str))
        """
        logger.info("---------- Getting Netease Cloud Music Data (this may take a few seconds) ----------")
        try:
            track_ids = [track_id["id"] for track_id in playlist["playlist"]["trackIds"]]
            
            # Apply limit if specified
            if limit > 0:
                track_ids = track_ids[:limit]
                logger.info(f"Limiting to first {limit} songs from playlist")
            
            songs = []
            # Split track_ids to pieces of length at most 1000 to avoid PyNCM API limitation
            left, right = 0, 0
            while right < len(track_ids):
                right = left + min(1000, len(track_ids) - right)
                songs.extend(apis.track.GetTrackDetail(track_ids[left:right])["songs"])
                left = right
            result = [(song["name"],
                      song["ar"][0]["name"], 
                      date.fromtimestamp(song["publishTime"] / MS_PER_S).year if "publishTime" in song and UNIX_START <= song["publishTime"] <= NEXT_YEAR else -1)
                     for song in songs]
            # Reverse the result
            return result[::-1]
        except Exception as e:
            logger.error(f"Failed to get Netease playlist tracks: {str(e)}")
            raise

    def get_base64_from_url(self, url):
        """
        Get the base64 representation of an image from a URL
        
        :param url: URL of the image to convert
        :return: base64 representation as string
        """
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx, 5xx)
            base64_str = base64.b64encode(response.content).decode("utf-8")
            if len(base64_str) > 256 * 1024:
                logger.error(f"Playlist cover image is too large to upload: {len(base64_str)} bytes")
                return None
            return base64_str
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch image from URL {url}: {str(e)}")
            return None

    def get_base64_from_image(self, path):
        """
        Get the base64 representation of an image

        :return: base64 representation
        :rtype: str
        """
        binary_fc = open(path, "rb").read()
        base64_utf8_str = base64.b64encode(binary_fc).decode("utf-8")
        return base64_utf8_str
        
    def search_for_track(self, year, name, artist=None):
        """
        Search for a track by name and artist (if provided)

        :return: the track's Spotify ID
        :rtype: str
        """
        query = ""
        # 9 years interval
        if year != -1:
            query += f"year:{year - 4}-{year + 4} "
        query += name
        if artist:
            query += " " + artist
        # Only search for the most relevant result (first)
        return self.spotify.search(query, limit=1, type="track")["tracks"]["items"][0]["id"]

    def get_playlist_tracks(self, playlist_id):
        """
        Get all track IDs from a Spotify playlist

        :param playlist_id: Spotify playlist ID
        :return: Set of track IDs
        """
        track_ids = set()
        offset = 0
        limit = 100  # Spotify API limit per request
        
        while True:
            results = self.spotify.playlist_items(
                playlist_id,
                offset=offset,
                limit=limit,
                fields='items.track.id,total'
            )
            
            if not results['items']:
                break
                
            for item in results['items']:
                if item['track'] and item['track']['id']:
                    track_ids.add(item['track']['id'])
                    
            offset += limit
            if offset >= results['total']:
                break
                
        return track_ids
