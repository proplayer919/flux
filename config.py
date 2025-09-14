"""
Configuration management for Flux containers
"""
import os
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, validator
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel

console = Console()

class ContainerConfig(BaseModel):
    """Container configuration model"""
    name: str = Field(..., description="Configuration name")
    distribution: str = Field(..., description="Linux distribution")
    version: str = Field(..., description="Distribution version")
    architecture: str = Field(default="amd64", description="Target architecture")
    packages: List[str] = Field(default_factory=list, description="Packages to install")
    custom_commands: List[str] = Field(default_factory=list, description="Custom commands to run")
    environment_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    ports: List[int] = Field(default_factory=list, description="Ports to expose")
    volumes: List[str] = Field(default_factory=list, description="Volume mounts")
    user: str = Field(default="root", description="Default user")
    working_dir: str = Field(default="/", description="Working directory")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    @validator('distribution')
    def validate_distribution(cls, v):
        supported_distros = ['ubuntu', 'debian', 'fedora', 'centos', 'alpine']
        if v.lower() not in supported_distros:
            raise ValueError(f"Unsupported distribution. Supported: {', '.join(supported_distros)}")
        return v.lower()
    
    @validator('architecture')
    def validate_architecture(cls, v):
        supported_archs = ['amd64', 'arm64', 'i386']
        if v not in supported_archs:
            raise ValueError(f"Unsupported architecture. Supported: {', '.join(supported_archs)}")
        return v

class ConfigManager:
    """Manages container configurations"""
    
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Use configs directory relative to project root
            self.config_dir = Path(__file__).parent / "configs"

        self.config_dir.mkdir(exist_ok=True)
    
    def create_interactive_config(self, name: str) -> Optional[ContainerConfig]:
        """Create a configuration interactively"""
        console.print("[bold blue]Container Configuration Setup[/bold blue]")
        console.print("Let's configure your Linux container step by step.\n")
        
        try:
            # Basic configuration
            distribution = self._prompt_distribution()
            version = self._prompt_version(distribution)
            architecture = self._prompt_architecture()
            
            # Package selection
            packages = self._prompt_packages()
            
            # Advanced options
            if Confirm.ask("Configure advanced options?", default=False):
                custom_commands = self._prompt_custom_commands()
                environment_vars = self._prompt_environment_vars()
                ports = self._prompt_ports()
                volumes = self._prompt_volumes()
                user = self._prompt_user()
                working_dir = self._prompt_working_dir()
            else:
                custom_commands = []
                environment_vars = {}
                ports = []
                volumes = []
                user = "root"
                working_dir = "/"
            
            config = ContainerConfig(
                name=name,
                distribution=distribution,
                version=version,
                architecture=architecture,
                packages=packages,
                custom_commands=custom_commands,
                environment_vars=environment_vars,
                ports=ports,
                volumes=volumes,
                user=user,
                working_dir=working_dir
            )
            
            # Show summary
            console.print("\n[bold green]Configuration Summary:[/bold green]")
            self.display_config(config)
            
            if Confirm.ask("\nSave this configuration?", default=True):
                return config
            else:
                return None
                
        except KeyboardInterrupt:
            console.print("\n[yellow]Configuration cancelled[/yellow]")
            return None
    
    def _prompt_distribution(self) -> str:
        """Prompt for Linux distribution"""
        distros = ["ubuntu", "debian", "fedora", "centos", "alpine"]
        
        console.print("[blue]Available distributions:[/blue]")
        for i, distro in enumerate(distros, 1):
            console.print(f"  {i}. {distro.title()}")
        
        while True:
            choice = Prompt.ask("Select distribution", choices=[str(i) for i in range(1, len(distros) + 1)], default="1")
            return distros[int(choice) - 1]
    
    def _prompt_version(self, distribution: str) -> str:
        """Prompt for distribution version"""
        version_map = {
            "ubuntu": ["22.04", "20.04", "18.04", "24.04"],
            "debian": ["12", "11", "10", "bookworm", "bullseye"],
            "fedora": ["39", "38", "37"],
            "centos": ["8", "7"],
            "alpine": ["3.18", "3.17", "latest"]
        }
        
        versions = version_map.get(distribution, ["latest"])
        
        console.print(f"\n[blue]Available {distribution.title()} versions:[/blue]")
        for i, version in enumerate(versions, 1):
            console.print(f"  {i}. {version}")
        
        choice = Prompt.ask("Select version", choices=[str(i) for i in range(1, len(versions) + 1)], default="1")
        return versions[int(choice) - 1]
    
    def _prompt_architecture(self) -> str:
        """Prompt for architecture"""
        archs = ["amd64", "arm64", "i386"]
        
        console.print(f"\n[blue]Available architectures:[/blue]")
        for i, arch in enumerate(archs, 1):
            console.print(f"  {i}. {arch}")
        
        choice = Prompt.ask("Select architecture", choices=[str(i) for i in range(1, len(archs) + 1)], default="1")
        return archs[int(choice) - 1]
    
    def _prompt_packages(self) -> List[str]:
        """Prompt for packages to install"""
        packages = []
        
        console.print(f"\n[blue]Package Installation:[/blue]")
        console.print("Enter packages to install (one per line, empty line to finish):")
        
        # Common package suggestions
        suggestions = {
            "ubuntu": ["curl", "wget", "git", "vim", "htop", "build-essential"],
            "debian": ["curl", "wget", "git", "vim", "htop", "build-essential"],
            "fedora": ["curl", "wget", "git", "vim", "htop", "gcc"],
            "centos": ["curl", "wget", "git", "vim", "htop", "gcc"],
            "alpine": ["curl", "wget", "git", "vim", "htop", "build-base"]
        }
        
        if Confirm.ask("Install common packages?", default=True):
            # This would be set based on the distribution chosen earlier
            # For now, using ubuntu as default
            common_packages = suggestions.get("ubuntu", [])
            packages.extend(common_packages)
            console.print(f"Added common packages: {', '.join(common_packages)}")
        
        console.print("Enter additional packages (empty line to finish):")
        while True:
            package = Prompt.ask("Package name", default="")
            if not package:
                break
            packages.append(package)
        
        return packages
    
    def _prompt_custom_commands(self) -> List[str]:
        """Prompt for custom commands"""
        commands = []
        
        console.print(f"\n[blue]Custom Commands:[/blue]")
        console.print("Enter custom commands to run during build (empty line to finish):")
        
        while True:
            command = Prompt.ask("Command", default="")
            if not command:
                break
            commands.append(command)
        
        return commands
    
    def _prompt_environment_vars(self) -> Dict[str, str]:
        """Prompt for environment variables"""
        env_vars = {}
        
        console.print(f"\n[blue]Environment Variables:[/blue]")
        console.print("Enter environment variables (format: KEY=VALUE, empty line to finish):")
        
        while True:
            env_var = Prompt.ask("Environment variable", default="")
            if not env_var:
                break
            
            if "=" in env_var:
                key, value = env_var.split("=", 1)
                env_vars[key.strip()] = value.strip()
            else:
                console.print("[yellow]Please use format: KEY=VALUE[/yellow]")
        
        return env_vars
    
    def _prompt_ports(self) -> List[int]:
        """Prompt for ports to expose"""
        ports = []
        
        console.print(f"\n[blue]Port Configuration:[/blue]")
        console.print("Enter ports to expose (empty line to finish):")
        
        while True:
            port = Prompt.ask("Port number", default="")
            if not port:
                break
            
            try:
                port_num = int(port)
                if 1 <= port_num <= 65535:
                    ports.append(port_num)
                else:
                    console.print("[yellow]Port must be between 1 and 65535[/yellow]")
            except ValueError:
                console.print("[yellow]Please enter a valid port number[/yellow]")
        
        return ports
    
    def _prompt_volumes(self) -> List[str]:
        """Prompt for volume mounts"""
        volumes = []
        
        console.print(f"\n[blue]Volume Mounts:[/blue]")
        console.print("Enter volume mounts (format: /host/path:/container/path, empty line to finish):")
        
        while True:
            volume = Prompt.ask("Volume mount", default="")
            if not volume:
                break
            volumes.append(volume)
        
        return volumes
    
    def _prompt_user(self) -> str:
        """Prompt for default user"""
        return Prompt.ask("\n[blue]Default user[/blue]", default="root")
    
    def _prompt_working_dir(self) -> str:
        """Prompt for working directory"""
        return Prompt.ask("[blue]Working directory[/blue]", default="/")
    
    def save_config(self, config: ContainerConfig) -> str:
        """Save configuration to JSON file"""
        config_file = self.config_dir / f"{config.name}.json"
        
        with open(config_file, 'w') as f:
            json.dump(config.dict(), f, indent=2)
        
        return str(config_file)
    
    def load_config(self, name: str) -> Optional[ContainerConfig]:
        """Load configuration from JSON file"""
        config_file = self.config_dir / f"{name}.json"
        
        if not config_file.exists():
            return None
        
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
            return ContainerConfig(**data)
        except Exception as e:
            console.print(f"[red]Error loading configuration: {e}[/red]")
            return None
    
    def list_configs(self) -> List[str]:
        """List all available configurations"""
        configs = []
        for config_file in self.config_dir.glob("*.json"):
            configs.append(config_file.stem)
        return sorted(configs)
    
    def delete_config(self, name: str) -> bool:
        """Delete a configuration"""
        config_file = self.config_dir / f"{name}.json"
        
        if config_file.exists():
            config_file.unlink()
            return True
        return False
    
    def display_config(self, config: ContainerConfig):
        """Display configuration in a formatted table"""
        table = Table(title=f"Configuration: {config.name}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Distribution", f"{config.distribution} {config.version}")
        table.add_row("Architecture", config.architecture)
        table.add_row("User", config.user)
        table.add_row("Working Directory", config.working_dir)
        
        if config.packages:
            table.add_row("Packages", ", ".join(config.packages))
        
        if config.custom_commands:
            table.add_row("Custom Commands", "\n".join(config.custom_commands))
        
        if config.environment_vars:
            env_str = "\n".join([f"{k}={v}" for k, v in config.environment_vars.items()])
            table.add_row("Environment Variables", env_str)
        
        if config.ports:
            table.add_row("Exposed Ports", ", ".join(map(str, config.ports)))
        
        if config.volumes:
            table.add_row("Volume Mounts", "\n".join(config.volumes))
        
        table.add_row("Created", config.created_at)
        
        console.print(table)
