"""
URL downloader for Flux configurations and images
"""

import os
import json
import requests
import hashlib
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse, unquote
from rich.console import Console
from rich.progress import (
    Progress,
    DownloadColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.panel import Panel
from rich.prompt import Confirm

from config import ConfigManager, ContainerConfig

console = Console()


class DownloadError(Exception):
    """Custom exception for download errors"""

    pass


class FluxDownloader:
    """Handles downloading configurations and images from URLs"""

    def __init__(
        self, config_dir: Optional[str] = None, images_dir: Optional[str] = None
    ):
        # Use config manager's directories if not specified
        config_manager = ConfigManager(config_dir)
        self.config_dir = config_manager.config_dir

        if images_dir:
            self.images_dir = Path(images_dir)
        else:
            self.images_dir = Path(__file__).parent / "images"

        self.images_dir.mkdir(exist_ok=True)

        # Create downloads directory for tracking
        self.downloads_dir = self.config_dir.parent / ".downloads"
        self.downloads_dir.mkdir(exist_ok=True)

    def download_config(
        self, url: str, name: Optional[str] = None, force: bool = False
    ) -> bool:
        """
        Download a configuration file from a URL

        Args:
            url: URL to download from
            name: Optional name to save the config as
            force: Whether to overwrite existing configs

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            console.print(f"[blue]Downloading configuration from: {url}[/blue]")

            # Download the file content
            response = self._download_with_progress(url)

            # Try to parse as JSON
            try:
                config_data = json.loads(response.content.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise DownloadError(f"Invalid JSON format: {e}")

            # Validate it's a proper config
            try:
                config = ContainerConfig(**config_data)
            except Exception as e:
                raise DownloadError(f"Invalid configuration format: {e}")

            # Determine the config name
            if name:
                config.name = name
            elif "name" not in config_data:
                # Generate name from URL
                parsed_url = urlparse(url)
                filename = Path(unquote(parsed_url.path)).stem
                config.name = filename if filename else "downloaded_config"

            # Check if config already exists
            config_manager = ConfigManager(str(self.config_dir))
            existing_configs = config_manager.list_configs()

            if config.name in existing_configs and not force:
                if not Confirm.ask(
                    f"Configuration '{config.name}' already exists. Overwrite?"
                ):
                    console.print("[yellow]Download cancelled[/yellow]")
                    return False

            # Save the configuration
            config_path = config_manager.save_config(config)

            # Record the download
            self._record_download(url, "config", config.name, config_path)

            console.print(f"[green]✓ Configuration saved as: {config.name}[/green]")
            console.print(f"[dim]Path: {config_path}[/dim]")

            return True

        except requests.RequestException as e:
            console.print(f"[red]Download failed: {e}[/red]")
            return False
        except DownloadError as e:
            console.print(f"[red]Error: {e}[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return False

    def download_image(
        self, url: str, name: Optional[str] = None, force: bool = False
    ) -> bool:
        """
        Download a container image from a URL

        Args:
            url: URL to download from
            name: Optional name to save the image as
            force: Whether to overwrite existing images

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            console.print(f"[blue]Downloading image from: {url}[/blue]")

            # Determine filename
            if name:
                filename = name
            else:
                parsed_url = urlparse(url)
                filename = Path(unquote(parsed_url.path)).name

            if not filename:
                filename = "downloaded_image.tar.gz"

            # Ensure proper extension
            if not any(
                filename.endswith(ext) for ext in [".tar.gz", ".tar.xz", ".tar"]
            ):
                filename += ".tar.gz"

            image_path = self.images_dir / filename

            # Check if image already exists
            if image_path.exists() and not force:
                if not Confirm.ask(f"Image '{filename}' already exists. Overwrite?"):
                    console.print("[yellow]Download cancelled[/yellow]")
                    return False

            # Download with progress bar
            response = self._download_with_progress(url)

            # Save to file
            with open(image_path, "wb") as f:
                f.write(response.content)

            # Verify file integrity (basic check)
            if image_path.stat().st_size != len(response.content):
                raise DownloadError("File size mismatch - download may be corrupted")

            # Record the download
            self._record_download(url, "image", filename, str(image_path))

            console.print(f"[green]✓ Image saved as: {filename}[/green]")
            console.print(f"[dim]Path: {image_path}[/dim]")
            console.print(
                f"[dim]Size: {self._format_size(image_path.stat().st_size)}[/dim]"
            )

            return True

        except requests.RequestException as e:
            console.print(f"[red]Download failed: {e}[/red]")
            return False
        except DownloadError as e:
            console.print(f"[red]Error: {e}[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return False

    def list_downloads(self) -> None:
        """List all downloaded files"""
        download_log = self.downloads_dir / "download_history.json"

        if not download_log.exists():
            console.print("[yellow]No downloads recorded[/yellow]")
            return

        try:
            with open(download_log, "r") as f:
                downloads = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            console.print("[yellow]No downloads recorded[/yellow]")
            return

        if not downloads:
            console.print("[yellow]No downloads recorded[/yellow]")
            return

        console.print("[blue]Download History:[/blue]")
        for download in downloads:
            download_type = download.get("type", "unknown")
            name = download.get("name", "unknown")
            url = download.get("url", "unknown")
            timestamp = download.get("timestamp", "unknown")

            console.print(f"  • [{download_type.upper()}] {name}")
            console.print(f"    URL: {url}")
            console.print(f"    Downloaded: {timestamp}")
            console.print()

    def _download_with_progress(self, url: str) -> requests.Response:
        """Download a file with a progress bar"""
        # Get file size first
        try:
            head_response = requests.head(url, timeout=10)
            total_size = int(head_response.headers.get("content-length", 0))
        except:
            total_size = 0

        # Start download
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        # If we couldn't get size from head request, try from get request
        if total_size == 0:
            total_size = int(response.headers.get("content-length", 0))

        if total_size > 0:
            # Download with progress bar
            content = bytearray()

            with Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
                "•",
                DownloadColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            ) as progress:

                task = progress.add_task("Downloading", total=total_size)

                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        content.extend(chunk)
                        progress.update(task, advance=len(chunk))

            # Create a new response object with the content
            new_response = requests.Response()
            new_response._content = bytes(content)
            new_response.status_code = response.status_code
            new_response.headers = response.headers
            return new_response
        else:
            # Download without progress bar
            console.print("[dim]Downloading (size unknown)...[/dim]")
            return response

    def _record_download(
        self, url: str, download_type: str, name: str, path: str
    ) -> None:
        """Record a download in the history"""
        download_log = self.downloads_dir / "download_history.json"

        # Load existing downloads
        downloads = []
        if download_log.exists():
            try:
                with open(download_log, "r") as f:
                    downloads = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                downloads = []

        # Add new download
        from datetime import datetime

        download_record = {
            "url": url,
            "type": download_type,
            "name": name,
            "path": path,
            "timestamp": datetime.now().isoformat(),
            "hash": self._calculate_url_hash(url),
        }

        downloads.append(download_record)

        # Save updated downloads
        with open(download_log, "w") as f:
            json.dump(downloads, f, indent=2)

    def _calculate_url_hash(self, url: str) -> str:
        """Calculate a hash for the URL"""
        return hashlib.md5(url.encode()).hexdigest()[:8]

    def _format_size(self, size: int) -> str:
        """Format file size in human readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def get_download_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get information about a URL before downloading"""
        try:
            console.print(f"[blue]Getting info for: {url}[/blue]")

            response = requests.head(url, timeout=10)
            response.raise_for_status()

            info = {
                "url": url,
                "content_type": response.headers.get("content-type", "unknown"),
                "content_length": response.headers.get("content-length"),
                "last_modified": response.headers.get("last-modified"),
                "server": response.headers.get("server"),
            }

            if info["content_length"]:
                info["size_formatted"] = self._format_size(int(info["content_length"]))

            # Display info
            console.print(
                Panel.fit(
                    f"Content Type: {info['content_type']}\n"
                    f"Size: {info.get('size_formatted', 'Unknown')}\n"
                    f"Last Modified: {info.get('last_modified', 'Unknown')}\n"
                    f"Server: {info.get('server', 'Unknown')}",
                    title="Download Info",
                    border_style="blue",
                )
            )

            return info

        except requests.RequestException as e:
            console.print(f"[red]Could not get info: {e}[/red]")
            return None
