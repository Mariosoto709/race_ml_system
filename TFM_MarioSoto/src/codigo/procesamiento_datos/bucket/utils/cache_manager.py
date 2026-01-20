"""
Manejador de cache para S3
"""
import os
import json
import hashlib
import boto3
from datetime import datetime
from urllib.parse import urlparse

class CacheManager:
    """Gestiona el cache de archivos procesados en S3"""
    
    def __init__(self, cache_s3_path):
        self.cache_s3_path = cache_s3_path
        parsed = urlparse(cache_s3_path)
        self.cache_bucket = parsed.netloc
        self.cache_key = f"{parsed.path.lstrip('/')}/file_cache.json"
        self.cache = self._load_cache_from_s3()
    
    def _load_cache_from_s3(self):
        """Carga el cache desde S3"""
        s3_client = boto3.client('s3')
        
        try:
            response = s3_client.get_object(Bucket=self.cache_bucket, Key=self.cache_key)
            cache_data = response['Body'].read().decode('utf-8')
            return json.loads(cache_data)
        except s3_client.exceptions.NoSuchKey:
            print("Cache no encontrado en S3, creando nuevo")
            return {}
        except Exception as e:
            print(f"Error cargando cache: {e}, creando nuevo")
            return {}
    
    def save_cache(self):
        """Guarda el cache en S3"""
        s3_client = boto3.client('s3')
        
        try:
            s3_client.put_object(
                Bucket=self.cache_bucket,
                Key=self.cache_key,
                Body=json.dumps(self.cache, indent=2),
                ContentType='application/json'
            )
            print(f"Cache guardado en S3: {len(self.cache)} entradas")
        except Exception as e:
            print(f"Error guardando cache en S3: {e}")
    
    def calculate_hash(self, s3_path):
        """Calcula hash MD5 de un archivo en S3"""
        parsed = urlparse(s3_path)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')
        
        s3_client = boto3.client('s3')
        
        try:
            # Usar ETag como hash aproximado
            response = s3_client.head_object(Bucket=bucket, Key=key)
            etag = response.get('ETag', '').strip('"')
            
            # Si el archivo es multipart, calcular hash manualmente
            if '-' in etag:
                # Para archivos grandes, usar tamaño y última modificación
                return f"{response.get('ContentLength')}-{response.get('LastModified').timestamp()}"
            
            return etag
        except Exception as e:
            print(f"Error calculando hash: {e}")
            return ""
    
    def get_file_metadata(self, s3_path):
        """Obtiene metadatos de un archivo en S3"""
        parsed = urlparse(s3_path)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')
        
        s3_client = boto3.client('s3')
        
        try:
            response = s3_client.head_object(Bucket=bucket, Key=key)
            
            return {
                "filename": key.split('/')[-1],
                "size": response.get('ContentLength', 0),
                "modified": response.get('LastModified', datetime.now()).timestamp(),
                "modified_date": response.get('LastModified', datetime.now()).isoformat(),
                "hash": self.calculate_hash(s3_path),
                "last_checked": datetime.now().isoformat(),
                "s3_path": s3_path
            }
        except Exception as e:
            print(f"Error obteniendo metadatos de {s3_path}: {e}")
            return None
    
    def check_file_changed(self, s3_path):
        """Verifica si un archivo en S3 ha cambiado"""
        filename = s3_path.split('/')[-1]
        
        if filename not in self.cache:
            return True, "Archivo nuevo"
        
        cached_data = self.cache[filename]
        current_metadata = self.get_file_metadata(s3_path)
        
        if not current_metadata:
            return True, "No se pudo leer metadatos"
        
        if current_metadata.get("hash") != cached_data.get("hash"):
            return True, "Contenido modificado (hash diferente)"
        
        if current_metadata.get("modified", 0) > cached_data.get("modified", 0):
            return True, "Fecha de modificación cambiada"
        
        return False, "Sin cambios"
    
    def update_cache(self, s3_path):
        """Actualiza el cache con un archivo procesado"""
        filename = s3_path.split('/')[-1]
        metadata = self.get_file_metadata(s3_path)
        
        if metadata:
            self.cache[filename] = metadata
            print(f"Cache actualizado para: {filename}")
    
    def get_cache_stats(self):
        """Obtiene estadísticas del cache"""
        total_size = sum(entry.get("size", 0) for entry in self.cache.values())
        
        return {
            "total_files": len(self.cache),
            "cache_size_mb": total_size / (1024 * 1024),
            "oldest_entry": min((entry.get("modified_date", "") for entry in self.cache.values()), default=""),
            "newest_entry": max((entry.get("modified_date", "") for entry in self.cache.values()), default="")
        }