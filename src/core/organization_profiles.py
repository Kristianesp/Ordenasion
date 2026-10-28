#!/usr/bin/env python3
"""
Perfiles de Organizacion para el Organizador de Archivos
Permite guardar y cargar configuraciones de organizacion personalizadas
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.utils.logger import warn


class OrganizationProfile:
    """Perfil de organizacion con configuracion personalizada"""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.created = datetime.now()
        self.modified = datetime.now()
        
        # Configuracion del perfil
        self.folder_path = ""
        self.move_folders = True
        self.similarity_threshold = 70
        self.selected_categories: List[str] = []
        self.custom_rules: List[Dict] = []
        self.exclude_patterns: List[str] = []
        self.max_file_size_mb = 0  # 0 = sin limite
        self.date_range: Dict[str, str] = {}  # start/end dates
        self.organize_by_date = False  # Organizar en subcarpetas por fecha
        self.dry_run = False  # Solo simular sin mover archivos
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para serializacion"""
        return {
            'name': self.name,
            'description': self.description,
            'created': self.created.isoformat(),
            'modified': self.modified.isoformat(),
            'folder_path': self.folder_path,
            'move_folders': self.move_folders,
            'similarity_threshold': self.similarity_threshold,
            'selected_categories': self.selected_categories,
            'custom_rules': self.custom_rules,
            'exclude_patterns': self.exclude_patterns,
            'max_file_size_mb': self.max_file_size_mb,
            'date_range': self.date_range,
            'organize_by_date': self.organize_by_date,
            'dry_run': self.dry_run
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OrganizationProfile':
        """Crea perfil desde diccionario"""
        profile = cls(
            name=data.get('name', 'Sin nombre'),
            description=data.get('description', '')
        )
        profile.folder_path = data.get('folder_path', '')
        profile.move_folders = data.get('move_folders', True)
        profile.similarity_threshold = data.get('similarity_threshold', 70)
        profile.selected_categories = data.get('selected_categories', [])
        profile.custom_rules = data.get('custom_rules', [])
        profile.exclude_patterns = data.get('exclude_patterns', [])
        profile.max_file_size_mb = data.get('max_file_size_mb', 0)
        profile.date_range = data.get('date_range', {})
        profile.organize_by_date = data.get('organize_by_date', False)
        profile.dry_run = data.get('dry_run', False)
        
        if 'created' in data:
            try:
                profile.created = datetime.fromisoformat(data['created'])
            except ValueError:
                pass
        if 'modified' in data:
            try:
                profile.modified = datetime.fromisoformat(data['modified'])
            except ValueError:
                pass
        
        return profile


class ProfileManager:
    """Gestor de perfiles de organizacion"""
    
    def __init__(self, profiles_file: Optional[str] = None):
        if profiles_file is None:
            from src.utils.paths import user_data_file
            profiles_file = str(user_data_file("organization_profiles.json"))
        self.profiles_file = profiles_file
        self.profiles: List[OrganizationProfile] = []
        self.active_profile: Optional[str] = None
        self.load_profiles()
    
    def create_profile(self, name: str, description: str = "") -> OrganizationProfile:
        """Crea un nuevo perfil"""
        # Verificar que no exista con el mismo nombre
        for p in self.profiles:
            if p.name.lower() == name.lower():
                raise ValueError(f"Ya existe un perfil con el nombre '{name}'")
        
        profile = OrganizationProfile(name, description)
        self.profiles.append(profile)
        self.save_profiles()
        return profile
    
    def delete_profile(self, name: str) -> bool:
        """Elimina un perfil por nombre"""
        for i, profile in enumerate(self.profiles):
            if profile.name.lower() == name.lower():
                del self.profiles[i]
                if self.active_profile == name:
                    self.active_profile = None
                self.save_profiles()
                return True
        return False
    
    def get_profile(self, name: str) -> Optional[OrganizationProfile]:
        """Obtiene un perfil por nombre"""
        for profile in self.profiles:
            if profile.name.lower() == name.lower():
                return profile
        return None
    
    def get_all_profiles(self) -> List[OrganizationProfile]:
        """Obtiene todos los perfiles"""
        return list(self.profiles)
    
    def get_profile_names(self) -> List[str]:
        """Obtiene los nombres de todos los perfiles"""
        return [p.name for p in self.profiles]
    
    def set_active_profile(self, name: str) -> bool:
        """Establece un perfil como activo"""
        if self.get_profile(name):
            self.active_profile = name
            self.save_profiles()
            return True
        return False
    
    def get_active_profile(self) -> Optional[OrganizationProfile]:
        """Obtiene el perfil activo"""
        if self.active_profile:
            return self.get_profile(self.active_profile)
        return None
    
    def update_profile(self, profile: OrganizationProfile) -> bool:
        """Actualiza un perfil existente"""
        for i, p in enumerate(self.profiles):
            if p.name.lower() == profile.name.lower():
                self.profiles[i] = profile
                profile.modified = datetime.now()
                self.save_profiles()
                return True
        return False
    
    def export_profile(self, name: str, filepath: str) -> bool:
        """Exporta un perfil a un archivo JSON"""
        profile = self.get_profile(name)
        if not profile:
            return False
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except (OSError, TypeError, ValueError) as exc:
            warn(f"No se pudo exportar el perfil {name}: {exc}")
            return False
    
    def import_profile(self, filepath: str) -> Optional[OrganizationProfile]:
        """Importa un perfil desde un archivo JSON"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            profile = OrganizationProfile.from_dict(data)
            
            # Evitar duplicados
            if self.get_profile(profile.name):
                profile.name = f"{profile.name} (importado)"
            
            self.profiles.append(profile)
            self.save_profiles()
            return profile
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            warn(f"No se pudo importar el perfil {filepath}: {exc}")
            return None
    
    def load_profiles(self) -> bool:
        """Carga los perfiles desde archivo"""
        try:
            path = Path(self.profiles_file)
            if path.exists():
                with open(self.profiles_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                profiles_data = data.get('profiles', [])
                self.profiles = [OrganizationProfile.from_dict(p) for p in profiles_data]
                self.active_profile = data.get('active_profile', None)
                return True
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            warn(f"No se pudieron cargar los perfiles: {exc}")
        
        # Si no se puede cargar, crear perfiles por defecto
        self._create_default_profiles()
        return False
    
    def save_profiles(self) -> bool:
        """Guarda los perfiles en archivo"""
        try:
            data = {
                'profiles': [p.to_dict() for p in self.profiles],
                'active_profile': self.active_profile
            }
            with open(self.profiles_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except (OSError, TypeError, ValueError) as exc:
            warn(f"No se pudieron guardar los perfiles: {exc}")
            return False
    
    def _create_default_profiles(self):
        """Crea perfiles por defecto"""
        # Perfil basico
        basic = OrganizationProfile(
            name="📁 Basico",
            description="Organizacion basica por categorias usando las extensiones de archivo"
        )
        basic.move_folders = True
        basic.similarity_threshold = 70
        self.profiles.append(basic)
        
        # Perfil solo archivos
        files_only = OrganizationProfile(
            name="📄 Solo Archivos",
            description="Organiza solo archivos, ignora las carpetas completas"
        )
        files_only.move_folders = False
        files_only.similarity_threshold = 60
        self.profiles.append(files_only)
        
        # Perfil por fecha
        date_profile = OrganizationProfile(
            name="📅 Por Fecha",
            description="Organiza archivos en subcarpetas por fecha de modificacion"
        )
        date_profile.organize_by_date = True
        date_profile.move_folders = True
        self.profiles.append(date_profile)
        
        self.save_profiles()
