"""
ETL INTELIGENTE - VERSIÓN TODO EN UNO PARA GLUE
Sin dependencias externas
"""
import sys
import json
import hashlib
import os
from datetime import datetime
from urllib.parse import urlparse
import boto3
import re

# Configuración de Glue
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, when, lit, explode
from pyspark.sql.types import StructType, StructField, StringType

print("=" * 60)
print("🚀 ETL INTELIGENTE - VERSIÓN TODO EN UNO")
print("=" * 60)

# ================= OBTENER PARÁMETROS =================
try:
    args = getResolvedOptions(sys.argv, [
        'JOB_NAME',
        'INPUT_S3_PATH',
        'OUTPUT_S3_PATH',
        'CACHE_S3_PATH'
    ])
    
    INPUT_S3_PATH = args['INPUT_S3_PATH']
    OUTPUT_S3_PATH = args['OUTPUT_S3_PATH']
    CACHE_S3_PATH = args['CACHE_S3_PATH']
    JOB_NAME = args['JOB_NAME']
    
except Exception as e:
    print(f"⚠️ Error obteniendo parámetros: {e}")
    print("Usando valores por defecto...")
    INPUT_S3_PATH = "s3://timingsense-glue-scripts/raw/athletes/"
    OUTPUT_S3_PATH = "s3://timingsense-glue-scripts/processed/"
    CACHE_S3_PATH = "s3://timingsense-glue-scripts/processed/.cache/"
    JOB_NAME = "etl_inteligente_job"

print(f"📁 Input S3: {INPUT_S3_PATH}")
print(f"💾 Output S3: {OUTPUT_S3_PATH}")
print(f"🗂️ Cache S3: {CACHE_S3_PATH}")
print(f"👷 Job: {JOB_NAME}")

# ================= INICIALIZAR SPARK =================
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(JOB_NAME, args)

# Configurar Spark para JSONs grandes
spark.conf.set("spark.sql.files.maxPartitionBytes", "134217728")  # 128MB
spark.conf.set("spark.sql.adaptive.enabled", "true")

# ================= CLASE CACHE MANAGER =================
class CacheManager:
    """Manejador de cache para archivos S3"""
    
    def __init__(self, cache_s3_path):
        self.cache_s3_path = cache_s3_path
        parsed = urlparse(cache_s3_path)
        self.cache_bucket = parsed.netloc
        self.cache_key = f"{parsed.path.lstrip('/')}/file_cache.json"
        self.cache = self._load_cache()
        print(f"✓ Cache cargado: {len(self.cache)} archivos registrados")
    
    def _load_cache(self):
        """Carga cache desde S3"""
        s3 = boto3.client('s3')
        try:
            response = s3.get_object(Bucket=self.cache_bucket, Key=self.cache_key)
            cache_data = json.loads(response['Body'].read().decode('utf-8'))
            print(f"  Cache cargado desde: s3://{self.cache_bucket}/{self.cache_key}")
            return cache_data
        except s3.exceptions.NoSuchKey:
            print("  No existe cache previo, creando nuevo")
            return {}
        except Exception as e:
            print(f"  Error cargando cache: {e}, creando nuevo")
            return {}
    
    def save_cache(self):
        """Guarda cache en S3"""
        s3 = boto3.client('s3')
        try:
            s3.put_object(
                Bucket=self.cache_bucket,
                Key=self.cache_key,
                Body=json.dumps(self.cache, indent=2),
                ContentType='application/json'
            )
            print(f"✓ Cache guardado: {len(self.cache)} archivos en s3://{self.cache_bucket}/{self.cache_key}")
        except Exception as e:
            print(f"❌ Error guardando cache: {e}")
    
    def get_file_metadata(self, s3_path):
        """Obtiene metadata de archivo S3"""
        parsed = urlparse(s3_path)
        s3 = boto3.client('s3')
        try:
            response = s3.head_object(Bucket=parsed.netloc, Key=parsed.path.lstrip('/'))
            etag = response['ETag'].strip('"')
            
            metadata = {
                "filename": parsed.path.split('/')[-1],
                "size_mb": round(response['ContentLength'] / (1024 * 1024), 2),
                "modified": response['LastModified'].timestamp(),
                "modified_date": response['LastModified'].isoformat(),
                "etag": etag,
                "last_checked": datetime.now().isoformat(),
                "s3_path": s3_path
            }
            return metadata
        except Exception as e:
            print(f"  ❌ Error obteniendo metadata de {s3_path}: {e}")
            return None
    
    def check_file_changed(self, s3_path):
        """Verifica si archivo cambió"""
        filename = s3_path.split('/')[-1]
        
        if filename not in self.cache:
            return True, "📦 NUEVO ARCHIVO"
        
        metadata = self.get_file_metadata(s3_path)
        if not metadata:
            return True, "❌ ERROR LEYENDO ARCHIVO"
        
        cached_etag = self.cache[filename].get('etag', '')
        current_etag = metadata.get('etag', '')
        
        if current_etag != cached_etag:
            return True, "🔄 CONTENIDO MODIFICADO"
        
        return False, "✅ SIN CAMBIOS"
    
    def update_cache(self, s3_path):
        """Actualiza cache con archivo procesado"""
        filename = s3_path.split('/')[-1]
        metadata = self.get_file_metadata(s3_path)
        if metadata:
            self.cache[filename] = metadata
            print(f"  ✓ Cache actualizado: {filename} ({metadata['size_mb']} MB)")
    
    def get_cache_stats(self):
        """Estadísticas del cache"""
        total_size = sum(entry.get('size_mb', 0) for entry in self.cache.values())
        return {
            "total_files": len(self.cache),
            "total_size_mb": round(total_size, 2),
            "oldest": min((e.get('modified_date', '') for e in self.cache.values()), default=''),
            "newest": max((e.get('modified_date', '') for e in self.cache.values()), default='')
        }

# ================= CLASE DATA PROCESSOR =================
class DataProcessor:
    """Procesa datos de atletas, eventos y tiempos"""
    
    # Columnas requeridas
    ATHLETES_COLUMNS = [
        'athlete_id', 'birthdate', 'club', 'fullName', 'gender', 'name',
        'nationality', 'race_id', 'surname'
    ]
    
    EVENTS_COLUMNS = [
        'athlete_id', 'auto_category', 'auto_chip', 'category', 'distance',
        'dorsal', 'event_id', 'gunTime', 'gunTimeMode', 'gunTimeModeConfig_wave',
        'last_split_seen', 'maxConsecutiveSplitsMissing', 'race_id', 'realStatus',
        'splitsMissing', 'splitsSeen', 'startNetTime', 'startRawTime', 'startTime',
        'status', 'team'
    ]
    
    TIMES_COLUMNS = [
        'athlete_id', 'average', 'distance', 'event_id', 'incidence', 'isBackup',
        'netTime', 'offset', 'order', 'race_id', 'rawTime', 'split', 'time'
    ]
    
    @staticmethod
    def extract_athlete_data(athlete_dict, race_id):
        """Extrae datos del atleta"""
        return {
            'race_id': race_id,
            'athlete_id': str(athlete_dict.get('id', '')),
            'birthdate': str(athlete_dict.get('birthdate', '')),
            'club': str(athlete_dict.get('club', '')),
            'fullName': str(athlete_dict.get('fullName', '')),
            'gender': str(athlete_dict.get('gender', '')),
            'name': str(athlete_dict.get('name', '')),
            'nationality': str(athlete_dict.get('nationality', '')),
            'surname': str(athlete_dict.get('surname', ''))
        }
    
    @staticmethod
    def extract_event_data(event_dict, athlete_id, race_id):
        """Extrae datos del evento"""
        event_data = {
            'race_id': race_id,
            'athlete_id': str(athlete_id),
            'event_id': str(event_dict.get('event') or event_dict.get('id') or f"event_{athlete_id}"),
            'auto_category': str(event_dict.get('auto_category', '')),
            'auto_chip': str(event_dict.get('auto_chip', '')),
            'category': str(event_dict.get('category', '')),
            'distance': str(event_dict.get('distance', '')),
            'dorsal': str(event_dict.get('dorsal', '')),
            'gunTime': str(event_dict.get('gunTime', '')),
            'gunTimeMode': str(event_dict.get('gunTimeMode', '')),
            'last_split_seen': str(event_dict.get('last_split_seen', '')),
            'maxConsecutiveSplitsMissing': str(event_dict.get('maxConsecutiveSplitsMissing', '')),
            'realStatus': str(event_dict.get('realStatus', '')),
            'splitsMissing': str(event_dict.get('splitsMissing', '')),
            'splitsSeen': str(event_dict.get('splitsSeen', '')),
            'startNetTime': str(event_dict.get('startNetTime', '')),
            'startRawTime': str(event_dict.get('startRawTime', '')),
            'startTime': str(event_dict.get('startTime', '')),
            'status': str(event_dict.get('status', '')),
            'team': str(event_dict.get('team', ''))
        }
        
        # Campo nested
        gun_config = event_dict.get('gunTimeModeConfig', {})
        if isinstance(gun_config, dict):
            event_data['gunTimeModeConfig_wave'] = str(gun_config.get('wave', ''))
        else:
            event_data['gunTimeModeConfig_wave'] = ''
        
        return event_data
    
    @staticmethod
    def extract_time_data(time_dict, split_name, athlete_id, event_id, race_id):
        """Extrae datos de tiempo"""
        return {
            'race_id': race_id,
            'athlete_id': str(athlete_id),
            'event_id': str(event_id),
            'split': str(split_name),
            'average': str(time_dict.get('average', '')),
            'distance': str(time_dict.get('distance', '')),
            'incidence': str(time_dict.get('incidence', '')),
            'isBackup': str(time_dict.get('isBackup', '')),
            'netTime': str(time_dict.get('netTime', '')),
            'offset': str(time_dict.get('offset', '')),
            'order': str(time_dict.get('order', '')),
            'rawTime': str(time_dict.get('rawTime', '')),
            'time': str(time_dict.get('time', ''))
        }
    
    def create_spark_dataframe(self, data_list, table_type):
        """Crea DataFrame Spark"""
        if table_type == "athletes":
            required_columns = self.ATHLETES_COLUMNS
        elif table_type == "events":
            required_columns = self.EVENTS_COLUMNS
        elif table_type == "times":
            required_columns = self.TIMES_COLUMNS
        else:
            raise ValueError(f"Tipo de tabla desconocido: {table_type}")
        
        if not data_list:
            print(f"  ⚠️ {table_type}: Sin datos")
            schema = StructType([StructField(col, StringType(), True) for col in required_columns])
            return spark.createDataFrame([], schema)
        
        # Convertir a DataFrame Spark
        rdd = spark.sparkContext.parallelize(data_list)
        df = spark.createDataFrame(rdd)
        
        # Asegurar columnas requeridas
        for col_name in required_columns:
            if col_name not in df.columns:
                df = df.withColumn(col_name, lit(""))
        
        # Seleccionar solo columnas requeridas
        df = df.select(required_columns)
        
        # Limpiar valores nulos
        for col_name in required_columns:
            df = df.withColumn(
                col_name,
                when(
                    (col(col_name).isNull()) | 
                    (col(col_name).isin('nan', 'null', 'None', 'NULL')),
                    ""
                ).otherwise(col(col_name))
            )
        
        # Eliminar duplicados
        df = df.dropDuplicates()
        
        print(f"  ✓ {table_type}: {df.count():,} registros, {len(df.columns)} columnas")
        return df

# ================= FUNCIONES DE ARCHIVOS =================
class S3FileUtils:
    """Utilidades para S3"""
    
    @staticmethod
    def get_json_files(s3_path):
        """Obtiene archivos JSON desde S3"""
        parsed = urlparse(s3_path)
        s3 = boto3.client('s3')
        
        json_files = []
        paginator = s3.get_paginator('list_objects_v2')
        
        try:
            for page in paginator.paginate(Bucket=parsed.netloc, Prefix=parsed.path.lstrip('/')):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        if obj['Key'].endswith('.json'):
                            json_files.append(f"s3://{parsed.netloc}/{obj['Key']}")
            
            print(f"📁 Encontrados {len(json_files)} archivos JSON")
            return json_files
            
        except Exception as e:
            print(f"❌ Error listando archivos en {s3_path}: {e}")
            return []
    
    @staticmethod
    def save_dataframe(df, table_name, output_s3_path):
        """Guarda DataFrame en Parquet"""
        if df.count() == 0:
            print(f"  ⚠️ {table_name}: DataFrame vacío, omitiendo")
            return None
        
        output_path = f"{output_s3_path.rstrip('/')}/{table_name}/"
        
        try:
            df.write \
                .mode('overwrite') \
                .option("compression", "snappy") \
                .parquet(output_path)
            
            print(f"  ✓ {table_name}: {df.count():,} registros guardados")
            print(f"    📍 {output_path}")
            return output_path
            
        except Exception as e:
            print(f"  ❌ Error guardando {table_name}: {e}")
            return None
    
    @staticmethod
    def save_metadata(metadata, output_s3_path):
        """Guarda metadatos del procesamiento"""
        parsed = urlparse(output_s3_path)
        s3 = boto3.client('s3')
        
        metadata_key = f"{parsed.path.lstrip('/')}/etl_metadata.json"
        
        try:
            s3.put_object(
                Bucket=parsed.netloc,
                Key=metadata_key,
                Body=json.dumps(metadata, indent=2, default=str),
                ContentType='application/json'
            )
            print(f"✓ Metadatos guardados: s3://{parsed.netloc}/{metadata_key}")
        except Exception as e:
            print(f"❌ Error guardando metadatos: {e}")

# ================= FUNCIÓN DE PROCESAMIENTO =================
def process_json_file(json_file, race_id, cache_manager, data_processor):
    """Procesa un archivo JSON individual"""
    print(f"\n🔄 Procesando: {json_file.split('/')[-1]}")
    
    try:
        # Leer JSON con Spark
        df = spark.read \
            .option("multiLine", "true") \
            .option("mode", "PERMISSIVE") \
            .json(json_file)
        
        # Para JSONs muy grandes, procesar por lotes
        if df.count() > 100000:
            print(f"  ⚡ JSON grande: {df.count():,} filas, procesando por lotes...")
            df = df.limit(100000)  # Limitar para prueba
        
        # Convertir a diccionarios
        data = df.toPandas().to_dict('records')
        
        all_athletes = []
        all_events = []
        all_times = []
        
        for athlete in data:
            if not isinstance(athlete, dict):
                continue
            
            athlete_id = athlete.get("id", "")
            
            # 1. Datos del atleta
            athlete_data = data_processor.extract_athlete_data(athlete, race_id)
            all_athletes.append(athlete_data)
            
            # 2. Eventos
            events = athlete.get("events", [])
            if not isinstance(events, list):
                events = [events] if events else []
            
            for event in events:
                if not isinstance(event, dict):
                    continue
                
                event_data = data_processor.extract_event_data(event, athlete_id, race_id)
                all_events.append(event_data)
                
                # 3. Tiempos
                times = event.get("times", {})
                if isinstance(times, dict):
                    for split_name, split_data in times.items():
                        if isinstance(split_data, dict):
                            time_data = data_processor.extract_time_data(
                                split_data, split_name, athlete_id, 
                                event_data['event_id'], race_id
                            )
                            all_times.append(time_data)
        
        print(f"  ✓ Extraídos: {len(all_athletes)} atletas, {len(all_events)} eventos, {len(all_times)} tiempos")
        
        # Actualizar cache
        cache_manager.update_cache(json_file)
        
        return all_athletes, all_events, all_times
        
    except Exception as e:
        print(f"❌ Error procesando {json_file}: {str(e)}")
        import traceback
        traceback.print_exc()
        return [], [], []

# ================= FUNCIÓN PRINCIPAL =================
def main():
    """Función principal del ETL"""
    print("\n" + "="*60)
    print("INICIANDO PROCESAMIENTO ETL")
    print("="*60)
    
    # Inicializar componentes
    cache_manager = CacheManager(CACHE_S3_PATH)
    data_processor = DataProcessor()
    file_utils = S3FileUtils()
    
    # Obtener archivos JSON
    json_files = file_utils.get_json_files(INPUT_S3_PATH)
    
    if not json_files:
        print("⚠️ No se encontraron archivos JSON para procesar")
        job.commit()
        return
    
    # Listas para resultados
    total_athletes = []
    total_events = []
    total_times = []
    
    files_to_process = 0
    files_skipped = 0
    
    # Procesar cada archivo
    for json_file in json_files[:5]:  # Procesar solo 5 archivos para prueba
        changed, reason = cache_manager.check_file_changed(json_file)
        
        if changed:
            print(f"\n✅ PROCESANDO: {json_file.split('/')[-1]}")
            print(f"   Razón: {reason}")
            files_to_process += 1
            
            # Extraer race_id del nombre
            race_id = re.sub(r'\.athletes\.json$|\.json$', '', json_file.split('/')[-1])
            
            # Procesar archivo
            athletes, events, times = process_json_file(
                json_file, race_id, cache_manager, data_processor
            )
            
            total_athletes.extend(athletes)
            total_events.extend(events)
            total_times.extend(times)
            
        else:
            print(f"\n⏭️ OMITIENDO: {json_file.split('/')[-1]}")
            print(f"   Razón: {reason}")
            files_skipped += 1
    
    # Resumen de cambios
    print("\n" + "="*60)
    print("📊 RESUMEN DE PROCESAMIENTO")
    print("="*60)
    print(f"  Archivos procesados: {files_to_process}")
    print(f"  Archivos omitidos: {files_skipped}")
    print(f"  Total archivos: {len(json_files)}")
    
    if files_to_process == 0:
        print("\n✅ No hay cambios. Nada que procesar.")
        cache_manager.save_cache()
        job.commit()
        return
    
    # Crear DataFrames
    print("\n" + "="*60)
    print("CREANDO DATAFRAMES")
    print("="*60)
    
    df_athletes = data_processor.create_spark_dataframe(total_athletes, "athletes")
    df_events = data_processor.create_spark_dataframe(total_events, "events")
    df_times = data_processor.create_spark_dataframe(total_times, "times")
    
    # Guardar datos
    print("\n" + "="*60)
    print("GUARDANDO DATOS EN S3")
    print("="*60)
    
    athletes_path = file_utils.save_dataframe(df_athletes, "athletes", OUTPUT_S3_PATH)
    events_path = file_utils.save_dataframe(df_events, "events", OUTPUT_S3_PATH)
    times_path = file_utils.save_dataframe(df_times, "times", OUTPUT_S3_PATH)
    
    # Guardar cache
    cache_manager.save_cache()
    cache_stats = cache_manager.get_cache_stats()
    
    # Guardar metadatos
    metadata = {
        "job_name": JOB_NAME,
        "processing_date": datetime.now().isoformat(),
        "input_path": INPUT_S3_PATH,
        "output_path": OUTPUT_S3_PATH,
        "cache_path": CACHE_S3_PATH,
        "processing_stats": {
            "files_processed": files_to_process,
            "files_skipped": files_skipped,
            "total_files": len(json_files)
        },
        "data_stats": {
            "athletes": int(df_athletes.count()) if df_athletes else 0,
            "events": int(df_events.count()) if df_events else 0,
            "times": int(df_times.count()) if df_times else 0
        },
        "cache_stats": cache_stats
    }
    
    file_utils.save_metadata(metadata, OUTPUT_S3_PATH)
    
    # Resumen final
    print("\n" + "="*60)
    print("🎉 ETL COMPLETADO EXITOSAMENTE")
    print("="*60)
    print(f"📈 DATOS PROCESADOS:")
    print(f"  • Atletas: {df_athletes.count() if df_athletes else 0:,} registros")
    print(f"  • Eventos: {df_events.count() if df_events else 0:,} registros")
    print(f"  • Tiempos: {df_times.count() if df_times else 0:,} registros")
    print(f"\n🗂️ ALMACENADO EN:")
    print(f"  • {athletes_path or 'N/A'}")
    print(f"  • {events_path or 'N/A'}")
    print(f"  • {times_path or 'N/A'}")
    print(f"\n📊 CACHE:")
    print(f"  • Archivos registrados: {cache_stats['total_files']}")
    print(f"  • Tamaño total: {cache_stats['total_size_mb']} MB")
    print("\n✅ Proceso terminado a las:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    # Commit del job
    job.commit()

# ================= EJECUCIÓN =================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR CRÍTICO: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)