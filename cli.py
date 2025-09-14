"""
Flux CLI - Main command line interface
"""

import os
import sys
import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm

from config import ConfigManager
from builder import ImageBuilder
from runner import ContainerRunner
from downloader import FluxDownloader

console = Console()


def print_banner():
    """Print the Flux banner"""
    banner = Text("FLUX", style="bold blue")
    subtitle = Text("Interactive Linux Container Configuration Tool", style="dim")
    console.print(Panel.fit(f"{banner}\n{subtitle}", border_style="blue"))


@click.group()
def cli():
    """Flux - Interactive Linux Container Configuration Tool"""
    print_banner()


@cli.command()
@click.option("--name", prompt="Configuration name", help="Name for the configuration")
def create(name):
    """Create a new container configuration interactively"""
    console.print(f"[green]Creating new configuration: {name}[/green]")

    config_manager = ConfigManager()
    config = config_manager.create_interactive_config(name)

    if config:
        config_path = config_manager.save_config(config)
        console.print(f"[green]✓ Configuration saved to: {config_path}[/green]")
    else:
        console.print("[red]Configuration creation cancelled[/red]")


@cli.command()
def list():
    """List all available configurations"""
    config_manager = ConfigManager()
    configs = config_manager.list_configs()

    if not configs:
        console.print("[yellow]No configurations found[/yellow]")
        return

    console.print("[blue]Available configurations:[/blue]")
    for config in configs:
        console.print(f"  • {config}")


@cli.command()
@click.argument("config_name")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed command output")
def build(config_name, verbose):
    """Build a container image from configuration"""
    console.print(f"[blue]Building image for configuration: {config_name}[/blue]")

    config_manager = ConfigManager()
    config = config_manager.load_config(config_name)

    if not config:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")
        return

    builder = ImageBuilder(verbose=verbose)
    try:
        image_path = builder.build_image(config)
        console.print(f"[green]✓ Image built successfully: {image_path}[/green]")
    except Exception as e:
        console.print(f"[red]Build failed: {e}[/red]")


@cli.command()
@click.argument("continuation_code")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed command output")
def build_continue(continuation_code, verbose):
    """Continue a failed build from where it left off"""
    console.print(f"[blue]Continuing build with code: {continuation_code}[/blue]")

    # Find the build state file to get the config name
    builder = ImageBuilder(verbose=verbose)
    state_dir = builder.images_dir / ".build_states"
    state_file = state_dir / f"{continuation_code}.json"

    if not state_file.exists():
        console.print(f"[red]Build state '{continuation_code}' not found[/red]")
        console.print(
            f"[yellow]Make sure the continuation code is correct and the build state hasn't been cleaned up[/yellow]"
        )
        return

    # Load the config name from the state file
    try:
        import json

        with open(state_file, "r") as f:
            state_data = json.load(f)
        config_name = state_data.get("config_name")

        if not config_name:
            console.print(f"[red]Invalid build state file - missing config name[/red]")
            return

    except Exception as e:
        console.print(f"[red]Error reading build state: {e}[/red]")
        return

    # Load the configuration
    config_manager = ConfigManager()
    config = config_manager.load_config(config_name)

    if not config:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")
        console.print(
            f"[yellow]The original configuration may have been deleted[/yellow]"
        )
        return

    try:
        image_path = builder.continue_build(continuation_code, config)
        console.print(f"[green]✓ Image built successfully: {image_path}[/green]")
    except Exception as e:
        console.print(f"[red]Build continuation failed: {e}[/red]")


@cli.command()
def build_states():
    """List all available build states for continuation"""
    builder = ImageBuilder()
    state_dir = builder.images_dir / ".build_states"

    if not state_dir.exists():
        console.print("[yellow]No build states found[/yellow]")
        return

    state_files = list(state_dir.glob("*.json"))

    if not state_files:
        console.print("[yellow]No build states found[/yellow]")
        return

    console.print("[blue]Available build states:[/blue]")

    import json
    import time

    for state_file in state_files:
        try:
            with open(state_file, "r") as f:
                state_data = json.load(f)

            build_id = state_data.get("build_id", "unknown")
            config_name = state_data.get("config_name", "unknown")
            started_at = state_data.get("started_at", 0)
            failed_step = state_data.get("failed_step", "unknown")

            # Format timestamp
            if started_at:
                started_str = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(started_at)
                )
            else:
                started_str = "unknown"

            console.print(
                f"  • {build_id} - {config_name} (failed at: {failed_step}, started: {started_str})"
            )

        except Exception as e:
            console.print(
                f"  • {state_file.stem} - [red]Error reading state: {e}[/red]"
            )


@cli.command()
@click.argument("build_id", required=False)
@click.option("--all", is_flag=True, help="Clean up all build states")
@click.confirmation_option(prompt="Are you sure you want to delete build state(s)?")
def build_cleanup(build_id, all):
    """Clean up build states and temporary directories"""
    builder = ImageBuilder()
    state_dir = builder.images_dir / ".build_states"

    if not state_dir.exists():
        console.print("[yellow]No build states found[/yellow]")
        return

    if all:
        # Clean up all build states
        import shutil
        import subprocess
        import json

        state_files = list(state_dir.glob("*.json"))
        cleaned = 0

        for state_file in state_files:
            try:
                # Try to clean up temp directory
                with open(state_file, "r") as f:
                    state_data = json.load(f)
                temp_dir = state_data.get("temp_dir")
                if temp_dir and Path(temp_dir).exists():
                    try:
                        subprocess.run(
                            ["sudo", "rm", "-rf", temp_dir],
                            check=True,
                            capture_output=True,
                        )
                    except:
                        pass  # Ignore cleanup errors

                # Remove state file
                state_file.unlink()
                cleaned += 1

            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not clean up {state_file.stem}: {e}[/yellow]"
                )

        console.print(f"[green]✓ Cleaned up {cleaned} build state(s)[/green]")

    elif build_id:
        # Clean up specific build state
        state_file = state_dir / f"{build_id}.json"

        if not state_file.exists():
            console.print(f"[red]Build state '{build_id}' not found[/red]")
            return

        try:
            # Try to clean up temp directory
            import json
            import subprocess

            with open(state_file, "r") as f:
                state_data = json.load(f)
            temp_dir = state_data.get("temp_dir")
            if temp_dir and Path(temp_dir).exists():
                try:
                    subprocess.run(
                        ["sudo", "rm", "-rf", temp_dir], check=True, capture_output=True
                    )
                    console.print(
                        f"[green]✓ Cleaned up temp directory: {temp_dir}[/green]"
                    )
                except:
                    console.print(
                        f"[yellow]Warning: Could not clean up temp directory: {temp_dir}[/yellow]"
                    )

            # Remove state file
            state_file.unlink()
            console.print(f"[green]✓ Cleaned up build state: {build_id}[/green]")

        except Exception as e:
            console.print(f"[red]Error cleaning up build state: {e}[/red]")
    else:
        console.print("[yellow]Please specify a build_id or use --all flag[/yellow]")


@cli.command()
@click.argument("config_name")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed command output")
def run(config_name, verbose):
    """Run a container from configuration"""
    console.print(f"[blue]Running container for: {config_name}[/blue]")

    config_manager = ConfigManager()
    config = config_manager.load_config(config_name)

    if not config:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")
        return

    runner = ContainerRunner(verbose=verbose)
    try:
        runner.run_container(config)
    except Exception as e:
        console.print(f"[red]Failed to run container: {e}[/red]")


@cli.command()
@click.argument("config_name")
def show(config_name):
    """Show configuration details"""
    config_manager = ConfigManager()
    config = config_manager.load_config(config_name)

    if not config:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")
        return

    config_manager.display_config(config)


@cli.command()
@click.argument("config_name")
@click.confirmation_option(prompt="Are you sure you want to delete this configuration?")
def delete(config_name):
    """Delete a configuration"""
    config_manager = ConfigManager()
    if config_manager.delete_config(config_name):
        console.print(f"[green]✓ Configuration '{config_name}' deleted[/green]")
    else:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")


@cli.command()
def images():
    """List all built images"""
    builder = ImageBuilder()
    image_list = builder.list_images()

    if not image_list:
        console.print("[yellow]No images found[/yellow]")
        return

    console.print("[blue]Built images:[/blue]")
    for image in image_list:
        size_mb = image["size"] / (1024 * 1024)
        console.print(f"  • {image['name']} ({size_mb:.1f} MB)")


@cli.command()
def ps():
    """List running containers"""
    runner = ContainerRunner()
    containers = runner.list_running_containers()

    if not containers:
        console.print("[yellow]No running containers[/yellow]")
        return

    console.print("[blue]Running containers:[/blue]")
    for container in containers:
        config_info = (
            f"config: {container.get('config', 'unknown')}"
            if "config" in container
            else container["class"]
        )
        console.print(f"  • {container['name']} ({config_info})")


@cli.command()
@click.argument("container_name")
def stop(container_name):
    """Stop a running container"""
    runner = ContainerRunner()
    if runner.stop_container(container_name):
        console.print(f"[green]✓ Container '{container_name}' stopped[/green]")
    else:
        console.print(f"[red]Failed to stop container '{container_name}'[/red]")


@cli.command()
@click.argument("config_name")
def edit(config_name):
    """Edit an existing configuration"""
    config_manager = ConfigManager()
    config = config_manager.load_config(config_name)

    if not config:
        console.print(f"[red]Configuration '{config_name}' not found[/red]")
        return

    console.print(f"[blue]Editing configuration: {config_name}[/blue]")
    console.print("[dim]Current configuration:[/dim]")
    config_manager.display_config(config)

    if not Confirm.ask("\nDo you want to edit this configuration?", default=True):
        return

    # Create new configuration with the same name
    new_config = config_manager.create_interactive_config(config_name)

    if new_config:
        config_path = config_manager.save_config(new_config)
        console.print(f"[green]✓ Configuration updated: {config_path}[/green]")
    else:
        console.print("[yellow]Configuration edit cancelled[/yellow]")


@cli.group()
def download():
    """Download configurations and images from URLs"""
    pass


@download.command()
@click.argument("url")
@click.option("--name", "-n", help="Name to save the configuration as")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing configuration without asking",
)
@click.option(
    "--info", "-i", is_flag=True, help="Show download info before downloading"
)
def config(url, name, force, info):
    """Download a configuration file from a URL"""
    downloader = FluxDownloader()

    if info:
        download_info = downloader.get_download_info(url)
        if not download_info:
            return

        if not Confirm.ask("Proceed with download?", default=True):
            console.print("[yellow]Download cancelled[/yellow]")
            return

    success = downloader.download_config(url, name, force)
    if not success:
        sys.exit(1)


@download.command()
@click.argument("url")
@click.option("--name", "-n", help="Name to save the image as")
@click.option(
    "--force", "-f", is_flag=True, help="Overwrite existing image without asking"
)
@click.option(
    "--info", "-i", is_flag=True, help="Show download info before downloading"
)
def image(url, name, force, info):
    """Download a container image from a URL"""
    downloader = FluxDownloader()

    if info:
        download_info = downloader.get_download_info(url)
        if not download_info:
            return

        if not Confirm.ask("Proceed with download?", default=True):
            console.print("[yellow]Download cancelled[/yellow]")
            return

    success = downloader.download_image(url, name, force)
    if not success:
        sys.exit(1)


@download.command()
def history():
    """Show download history"""
    downloader = FluxDownloader()
    downloader.list_downloads()


def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
