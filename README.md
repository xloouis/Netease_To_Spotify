<p align="center"><img src="assets/cover.png" /></p>

# 网易云音乐歌单迁移至Spotify

Forked from [Netease-to-Spotify](https://github.com/muyangye/Netease_To_Spotify)

## Added

- Support migrating multiple playlists
- Add prefix to playlist name
- Configurable logging with retention policies
- Token caching for background operation
- Automatic token refresh

## Configuration

The `config.yml` file supports the following configuration:

```yaml
client_id: "YOUR_CLIENT_ID_HERE"
client_secret: "YOUR_CLIENT_SECRET_HERE"
playlist_prefix: "[NetEase]"  # Optional prefix for all migrated playlists
cover_image_path: "DESIRED_SPOTIFY_PLAYLIST_COVER_IMAGE_PATH"
netease_playlists:  # List of playlists to migrate with their limits
  - id: "YOUR_FIRST_NETEASE_PLAYLIST_ID"
    limit: 50  # Optional: limit to first 50 songs (remove or set to 0 for no limit)
  - id: "YOUR_SECOND_NETEASE_PLAYLIST_ID"
    limit: 100  # Optional: limit to first 100 songs
logging:
  directory: "logs"  # Directory to store log files
  retention:
    max_size_gb: 5  # Maximum total size of log files in gigabytes
    max_days: 30    # Maximum age of log files in days
  level: "INFO"     # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Features

### Multiple Playlist Migration with Limits
- Migrate multiple playlists in one go by listing their IDs in the `netease_playlists` configuration
- Optionally limit the number of songs to migrate from each playlist
- Each playlist can have its own limit, or no limit at all

### Playlist Prefix
Add a prefix to all migrated playlist names using the `playlist_prefix` configuration.

### Logging System
- Logs are stored in daily files (e.g., `2024-12-08.log`)
- Configurable retention policies:
  - Size-based: Remove oldest logs when total size exceeds limit
  - Age-based: Remove logs older than specified days
- Different logging levels for detailed debugging
- Logs are stored in the configured directory (default: `logs/`)

### Token System
- First-time run requires browser authentication
- Subsequent runs use cached token (no browser needed)
- Token validity:
  - Access token: Valid for 1 hour
  - Refresh token: Valid indefinitely (until revoked)
  - Automatic refresh when access token expires
- Token is stored in `.spotify_token.json`
- Token remains valid unless:
  - You revoke access in Spotify account settings
  - The app is removed from your Spotify account
  - The client secret is changed

## Running
1. Install dependencies: `pip install -r requirements.txt`
2. [Create Spotify app](https://developer.spotify.com/documentation/web-api/concepts/apps) (if you don't have one)
3. Configure `config.yml` with your settings
4. First run: `python cli.py` and complete the one-time browser authentication
5. Subsequent runs can be done in background: `python cli.py &`
6. The migration will proceed automatically, with progress logged to both console and log files

### Running in Background
After the initial authentication:
1. The token is cached in `.spotify_token.json`
2. You can run the script in background: `python cli.py &`
3. Check the logs directory for progress

### Token Troubleshooting
If authentication fails:
1. Check if your client_id and client_secret are correct
2. Verify the app still exists in your Spotify account
3. Check if you haven't revoked access for this app
4. If issues persist, delete `.spotify_token.json` and re-authenticate
