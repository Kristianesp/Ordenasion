#!/usr/bin/env python3
"""
Gestor de Categorías para el Organizador de Archivos
Maneja la lógica de categorías, extensiones y operaciones CRUD
"""

import json
import re
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

from src.utils.constants import CATEGORIAS, VARIOS_FOLDER


class CategoryRule:
    """Regla personalizada para categorización"""

    def __init__(self, name: str, pattern: str, category: str, priority: int = 0):
        self.name = name
        self.pattern = pattern  # Regex pattern o string
        self.category = category
        self.priority = priority
        self.enabled = True
        self.created_date = datetime.now()

    def matches(self, file_path: Path) -> bool:
        """Verifica si el archivo coincide con esta regla"""
        if not self.enabled:
            return False

        try:
            # Compilar patrón si es regex
            if self.pattern.startswith('regex:'):
                pattern = self.pattern[6:]  # Quitar prefijo 'regex:'
                compiled_pattern = re.compile(pattern, re.IGNORECASE)
                return bool(compiled_pattern.search(str(file_path)))
            else:
                # Búsqueda simple por nombre
                return self.pattern.lower() in file_path.name.lower()
        except:
            return False


class CategoryManager:
    """Gestor principal de categorías y extensiones"""

    def __init__(self, config_file: Optional[str] = None):
        if config_file is None:
            from src.utils.paths import user_data_file
            config_file = str(user_data_file("categories_config.json"))
        self.config_file = config_file
        self.categories = CATEGORIAS.copy()
        self.ext_to_categoria = self._create_reverse_index()
        self.custom_rules: List[CategoryRule] = []
        self.nested_categories: Dict[str, List[str]] = {}  # Categorías anidadas
        self.load_configuration()
    
    def _create_reverse_index(self) -> Dict[str, str]:
        """Crea el índice inverso de extensiones a categorías"""
        ext_to_cat = {}
        for categoria, extensiones in self.categories.items():
            for ext in extensiones:
                ext_to_cat[ext.lower()] = categoria
        return ext_to_cat
    
    def get_categories(self) -> Dict[str, List[str]]:
        """Retorna las categorías actuales"""
        return self.categories.copy()
    
    def get_extensions_for_category(self, category: str) -> List[str]:
        """Retorna las extensiones de una categoría específica"""
        return self.categories.get(category, []).copy()
    
    def get_category_for_extension(self, extension: str) -> Optional[str]:
        """Retorna la categoría para una extensión específica"""
        return self.ext_to_categoria.get(extension.lower())
    
    def add_category(self, name: str, extensions: List[str]) -> bool:
        """Añade una nueva categoría"""
        if name in self.categories:
            return False
        
        self.categories[name] = extensions.copy()
        self._update_reverse_index()
        return True
    
    def remove_category(self, name: str) -> bool:
        """Elimina una categoría (solo personalizadas)"""
        # No permitir eliminar categorías del sistema
        if name in CATEGORIAS:
            return False
        
        if name in self.categories:
            del self.categories[name]
            self._update_reverse_index()
            return True
        return False
    
    def add_extension_to_category(self, category: str, extension: str) -> bool:
        """Añade una extensión a una categoría"""
        if category not in self.categories:
            return False
        
        if extension not in self.categories[category]:
            self.categories[category].append(extension)
            self._update_reverse_index()
            return True
        return False
    
    def remove_extension_from_category(self, category: str, extension: str) -> bool:
        """Elimina una extensión de una categoría"""
        if category not in self.categories:
            return False
        
        if extension in self.categories[category]:
            self.categories[category].remove(extension)
            self._update_reverse_index()
            return True
        return False
    
    def update_category(self, name: str, extensions: List[str]) -> bool:
        """Actualiza una categoría existente"""
        if name not in self.categories:
            return False
        
        self.categories[name] = extensions.copy()
        self._update_reverse_index()
        return True
    
    def _update_reverse_index(self):
        """Actualiza el índice inverso después de cambios"""
        self.ext_to_categoria = self._create_reverse_index()
    
    def get_system_categories(self) -> List[str]:
        """Retorna las categorías del sistema (no eliminables)"""
        return list(CATEGORIAS.keys())
    
    def get_custom_categories(self) -> List[str]:
        """Retorna las categorías personalizadas (eliminables)"""
        return [cat for cat in self.categories.keys() if cat not in CATEGORIAS]
    
    def is_system_category(self, category: str) -> bool:
        """Verifica si una categoría es del sistema"""
        return category in CATEGORIAS
    
    def reset_to_default(self):
        """Restaura las categorías por defecto"""
        self.categories = CATEGORIAS.copy()
        self._update_reverse_index()
        self.save_configuration()
    
    def get_stats(self) -> Dict[str, int]:
        """Retorna estadísticas de las categorías"""
        stats = {}
        for category, extensions in self.categories.items():
            stats[category] = len(extensions)
        return stats
    
    def export_to_txt(self, filepath: str) -> bool:
        """Exporta las categorías a un archivo de texto"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("📁 CATEGORÍAS Y EXTENSIONES\n")
                f.write("=" * 50 + "\n\n")
                
                for category, extensions in self.categories.items():
                    f.write(f"📂 {category}\n")
                    f.write("-" * 30 + "\n")
                    for ext in extensions:
                        f.write(f"  • {ext}\n")
                    f.write(f"\nTotal: {len(extensions)} extensiones\n\n")
                
                f.write(f"📊 TOTAL: {len(self.categories)} categorías\n")
                f.write(f"📄 TOTAL: {sum(len(exts) for exts in self.categories.values())} extensiones\n")
            
            return True
        except Exception:
            return False
    
    def save_configuration(self) -> bool:
        """Guarda la configuración en archivo JSON"""
        try:
            # Convertir reglas a formato serializable
            rules_data = []
            for rule in self.custom_rules:
                rules_data.append({
                    'name': rule.name,
                    'pattern': rule.pattern,
                    'category': rule.category,
                    'priority': rule.priority,
                    'enabled': rule.enabled,
                    'created_date': rule.created_date.isoformat()
                })

            config_data = {
                'categories': self.categories,
                'ext_to_categoria': self.ext_to_categoria,
                'custom_rules': rules_data,
                'nested_categories': self.nested_categories
            }

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

            return True
        except Exception:
            return False
    
    def load_configuration(self) -> bool:
        """Carga la configuración desde archivo JSON"""
        try:
            # ⚠️ CRÍTICO: En .exe, los archivos pueden no estar disponibles durante __init__
            # Si falla, continuar con configuración por defecto
            config_path = Path(self.config_file)
            if config_path.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                if 'categories' in config_data:
                    self.categories = config_data['categories']
                    self._update_reverse_index()

                # Cargar reglas personalizadas
                if 'custom_rules' in config_data:
                    self.custom_rules = []
                    for rule_data in config_data['custom_rules']:
                        rule = CategoryRule(
                            rule_data['name'],
                            rule_data['pattern'],
                            rule_data['category'],
                            rule_data['priority']
                        )
                        rule.enabled = rule_data.get('enabled', True)
                        if 'created_date' in rule_data:
                            try:
                                rule.created_date = datetime.fromisoformat(rule_data['created_date'])
                            except:
                                pass
                        self.custom_rules.append(rule)

                # Cargar categorías anidadas
                if 'nested_categories' in config_data:
                    self.nested_categories = config_data['nested_categories']

                return True
        except Exception:
            pass

        # Si no se puede cargar, usar valores por defecto
        self.categories = CATEGORIAS.copy()
        self._update_reverse_index()
        return False
    
    def get_varios_folder(self) -> str:
        """Retorna el nombre de la carpeta para archivos no categorizados"""
        return VARIOS_FOLDER
    
    def categorize_file(self, file_path: Path) -> str:
        """Categoriza un archivo usando reglas personalizadas y extensión"""
        # Primero verificar reglas personalizadas (ordenadas por prioridad)
        for rule in sorted(self.custom_rules, key=lambda r: r.priority, reverse=True):
            if rule.matches(file_path):
                return rule.category

        # Si no hay reglas personalizadas, usar categorización por extensión
        extension = file_path.suffix.lower()
        return self.ext_to_categoria.get(extension, "VARIOS")

    def add_custom_rule(self, name: str, pattern: str, category: str, priority: int = 0) -> bool:
        """Añade una regla personalizada de categorización"""
        rule = CategoryRule(name, pattern, category, priority)
        self.custom_rules.append(rule)
        self.save_configuration()
        return True

    def remove_custom_rule(self, name: str) -> bool:
        """Elimina una regla personalizada"""
        for i, rule in enumerate(self.custom_rules):
            if rule.name == name:
                del self.custom_rules[i]
                self.save_configuration()
                return True
        return False

    def create_nested_category(self, parent_category: str, child_category: str) -> bool:
        """Crea una categoría anidada (hija de otra)"""
        if parent_category not in self.categories:
            return False

        if parent_category not in self.nested_categories:
            self.nested_categories[parent_category] = []

        if child_category not in self.nested_categories[parent_category]:
            self.nested_categories[parent_category].append(child_category)

        self.save_configuration()
        return True

    def get_nested_categories(self, category: str) -> List[str]:
        """Obtiene las categorías hijas de una categoría"""
        return self.nested_categories.get(category, [])

    def get_all_nested_paths(self, category: str) -> List[str]:
        """Obtiene todas las rutas anidadas de una categoría"""
        paths = [category]
        children = self.get_nested_categories(category)

        for child in children:
            paths.extend(self.get_all_nested_paths(child))

        return paths

    def get_category_with_hierarchy(self, file_path: Path) -> str:
        """Obtiene la categoría completa con jerarquía para un archivo"""
        base_category = self.categorize_file(file_path)

        # Si tiene categorías anidadas, intentar asignar subcategoría
        nested_cats = self.get_nested_categories(base_category)
        if nested_cats:
            # Por simplicidad, usar la primera subcategoría
            # En el futuro se podría hacer más inteligente
            return nested_cats[0]

        return base_category

    def analyze_category_distribution(self, files: List[Path]) -> Dict[str, int]:
        """Analiza la distribución de archivos por categoría"""
        distribution = {}

        for file_path in files:
            category = self.categorize_file(file_path)
            distribution[category] = distribution.get(category, 0) + 1

        return distribution

    def suggest_new_categories(self, files: List[Path], min_files: int = 5) -> List[str]:
        """Sugiere nuevas categorías basadas en archivos sin categorizar"""
        uncategorized = []

        for file_path in files:
            category = self.categorize_file(file_path)
            if category == "VARIOS" and file_path.suffix:
                ext = file_path.suffix.lower()
                if ext not in uncategorized:
                    uncategorized.append(ext)

        # Sugerir categorías para extensiones con muchos archivos
        suggestions = []
        for ext in uncategorized:
            count = sum(1 for f in files if f.suffix.lower() == ext)
            if count >= min_files:
                suggestions.append(ext)

        return suggestions
    
    def get_all_extensions(self) -> List[str]:
        """Retorna todas las extensiones disponibles"""
        all_exts = []
        for extensions in self.categories.values():
            all_exts.extend(extensions)
        return sorted(list(set(all_exts)))
    
    def validate_extension(self, extension: str) -> bool:
        """Valida si una extensión tiene el formato correcto"""
        return extension.startswith('.') and len(extension) > 1
    
    def get_category_info(self, category: str) -> Dict[str, any]:
        """Retorna información detallada de una categoría"""
        if category not in self.categories:
            return {}
        
        return {
            'name': category,
            'extensions': self.categories[category].copy(),
            'extension_count': len(self.categories[category]),
            'is_system': self.is_system_category(category)
        }
