# Imports necesarios
import tweepy
import time
import os
import requests
import logging
import tempfile

# --- Configuración ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Leer credenciales desde variables de entorno (proporcionadas por GitHub Actions Secrets)
API_KEY = os.getenv("TWITTER_API_KEY")
API_SECRET = os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# --- Configuración del Repositorio de GIFs ---
# URL base de la carpeta en GitHub Raw (donde están 1.gif, 2.gif...)
GIF_BASE_URL = "https://raw.githubusercontent.com/GoonLibrary/GifGallery/main/"
# Número total de GIFs (el número del último archivo, ej: 111 para 111.gif)
TOTAL_GIF_COUNT = 111 # ¡¡¡RECUERDA ACTUALIZAR ESTO!!!
# Ruta relativa al archivo que guarda el índice (debe existir en el repo)
STATE_FILE_PATH = "state/next_gif_index.txt"

# --- Funciones Auxiliares ---
def read_next_index():
    """Lee el índice (0-based) desde el archivo de estado en el repo."""
    try:
        # Usar la ruta relativa definida
        if os.path.exists(STATE_FILE_PATH):
            with open(STATE_FILE_PATH, 'r') as f:
                content = f.read().strip()
                logging.info(f"Índice leído de '{STATE_FILE_PATH}': '{content}'")
                # Devolver 0 si está vacío o no es un número válido
                return int(content) if content.isdigit() else 0
        else:
            # Si el archivo no existe (no debería pasar si se configura bien el repo)
            logging.warning(f"Archivo de estado '{STATE_FILE_PATH}' no encontrado! Empezando desde 0.")
            return 0
    except (ValueError, IOError) as e:
        logging.error(f"Error leyendo '{STATE_FILE_PATH}': {e}. Empezando desde 0.")
        return 0
    except Exception as e: # Captura otros posibles errores
        logging.error(f"Error inesperado leyendo índice: {e}. Empezando desde 0.")
        return 0

def write_next_index(index):
    """Escribe el índice (0-based) en el archivo de estado en el repo."""
    try:
        # Usar la ruta relativa definida
        with open(STATE_FILE_PATH, 'w') as f:
            f.write(str(index))
        logging.info(f"Nuevo índice ({index}) escrito en '{STATE_FILE_PATH}'. (Necesita commit/push por la Action)")
    except IOError as e:
        logging.error(f"Error escribiendo en '{STATE_FILE_PATH}': {e}")
    except Exception as e:
        logging.error(f"Error inesperado escribiendo índice: {e}")


def authenticate_twitter():
    """Autentica con Twitter API v1.1 y v2."""
    try:
        # Verificar que las credenciales se leyeron del entorno
        if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
            logging.error("Una o más credenciales de Twitter no están definidas en las variables de entorno.")
            return None, None

        client_v2 = tweepy.Client(
            consumer_key=API_KEY, consumer_secret=API_SECRET,
            access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET,
            wait_on_rate_limit=True
        )
        auth_v1 = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
        api_v1 = tweepy.API(auth_v1, wait_on_rate_limit=True)
        # Verificar credenciales con una llamada simple
        user = api_v1.verify_credentials()
        logging.info(f"Autenticación Twitter v1.1 (usuario {user.screen_name}) y v2 OK.")
        return client_v2, api_v1
    except tweepy.errors.TweepyException as e:
        logging.error(f"Error de autenticación con Tweepy: {e}")
        return None, None
    except Exception as e:
        logging.error(f"Error inesperado durante la autenticación: {e}", exc_info=True)
        return None, None

# --- Función Principal (Descarga a Archivo Temporal, Nombres X.gif, Espera Corta) ---
def post_gif_from_temp_file(client_v2, api_v1):
    """Descarga GIF (X.gif) a temp, sube (v1), espera, publica (v2)."""
    if not client_v2 or not api_v1:
        logging.error("Clientes API no inicializados.")
        return False # Indicar fallo
    if not GIF_BASE_URL or TOTAL_GIF_COUNT <= 0:
        logging.error("Error config GIF_BASE_URL o TOTAL_GIF_COUNT.")
        return False # Indicar fallo

    media_id = None
    success = False
    temp_gif_path = None # Para asegurarnos de que se elimina

    try:
        current_index = read_next_index() # Índice basado en 0
        # Validar índice
        if current_index < 0 or current_index >= TOTAL_GIF_COUNT:
            logging.warning(f"Índice {current_index} fuera de rango [0-{TOTAL_GIF_COUNT-1}]. Reiniciando a 0.")
            current_index = 0

        # --- Generar nombre de archivo y URL ---
        gif_number = current_index + 1 # Número real del GIF (1, 2, 3...)
        gif_filename = f"{gif_number}.gif" # Nombre simple: 1.gif, 2.gif, etc.
        selected_gif_url = GIF_BASE_URL.strip('/') + '/' + gif_filename # Asegurar una sola barra
        logging.info(f"Índice: {current_index}. Intentando con GIF #{gif_number} desde: {selected_gif_url}")

        logging.info(f"Descargando GIF: {selected_gif_url}...")
        try:
            response = requests.get(selected_gif_url, timeout=90) # Timeout de descarga
            response.raise_for_status() # Lanza error si es 404, etc.
            gif_content = response.content
            logging.info(f"Descarga completa. Tamaño: {len(gif_content)} bytes.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error descarga ({selected_gif_url}): {e}. ¿Archivo {gif_filename} existe en GitHub?")
            return False

        # --- Guardar en archivo temporal ---
        # Usar mkstemp para obtener la ruta de forma segura
        fd, temp_gif_path = tempfile.mkstemp(suffix=".gif")
        logging.info(f"Creando archivo temporal: {temp_gif_path}")
        # Asegurarse de usar el file descriptor para escribir binario
        with os.fdopen(fd, 'wb') as temp_file:
            temp_file.write(gif_content)
        logging.info(f"GIF guardado temporalmente en: {temp_gif_path}")

        # --- Subir DESDE el archivo temporal usando API v1.1 ---
        logging.info(f"Subiendo GIF desde archivo temporal {temp_gif_path} (v1.1)...")
        # Quitar media_category temporalmente para ver si interfiere menos
        media = api_v1.media_upload(filename=temp_gif_path)
        media_id = media.media_id_string
        # Comprobar si se obtuvo un ID válido
        if not media_id:
             logging.error("Fallo crítico: No se obtuvo Media ID válido después de la subida desde archivo.")
             if temp_gif_path and os.path.exists(temp_gif_path): os.remove(temp_gif_path) # Limpiar
             return False
        logging.info(f"GIF subido desde archivo. Media ID: {media_id}")

        # --- Espera antes de publicar con v2 ---
        wait_time = 30 # Usar 30 segundos que funcionaron para reproducción
        logging.info(f"Esperando {wait_time} segundos antes de publicar con v2...")
        time.sleep(wait_time)

        # --- Publicar Tweet usando API v2 ---
        logging.info(f"Publicando tweet (v2) con Media ID: {media_id} y hashtags...")
        # Volver a comprobar media_id por si acaso
        if media_id:
            tweet_text = "#GOON #GOONER #GOONETTE #PORN #CNC #FREEUSE #GOONED" # Tus hashtags
            tweet_response = client_v2.create_tweet(
                text=tweet_text,
                media_ids=[media_id]
            )
            logging.info(f"Tweet publicado (v2)! ID: {tweet_response.data['id']}")

            # Actualizar índice para la próxima ejecución SOLO si todo fue bien
            next_index = (current_index + 1) % TOTAL_GIF_COUNT
            write_next_index(next_index) # Guardar en state/next_gif_index.txt
            success = True # Marcar como éxito
        else:
             logging.error("Error crítico: Media ID se volvió nulo antes de publicar.")
             return False

    except tweepy.errors.TweepyException as e:
        # Capturar errores de Tweepy (API) durante la publicación
        error_msg = f"Error de Tweepy durante publicación v2 (Media ID intentado: {media_id}): {e}"
        logging.error(error_msg)
        # No actualizamos el índice si hay error
        return False
    except Exception as e:
        # Capturar cualquier otro error inesperado
        logging.error(f"Error inesperado durante el proceso: {e}", exc_info=True)
        return False
    finally:
        # --- Asegurarse de eliminar el archivo temporal SIEMPRE ---
        if temp_gif_path and os.path.exists(temp_gif_path):
            try:
                os.remove(temp_gif_path)
                logging.info(f"Archivo temporal {temp_gif_path} eliminado.")
            except OSError as e:
                # Registrar error si no se puede borrar, pero no detener el script
                logging.error(f"Error al eliminar archivo temporal {temp_gif_path}: {e}")

    return success # Devolver True si todo OK, False si hubo algún error

# --- Función Job ---
def job():
    """Función principal que se ejecutará en la GitHub Action."""
    logging.info("Ejecutando Job: Descarga (X.gif) a temp, Subir (v1), esperar, publicar (v2) con hashtags.")
    client_v2, api_v1 = authenticate_twitter()
    if client_v2 and api_v1:
        # Llamar a la función que usa archivo temporal y nombres simples
        if not post_gif_from_temp_file(client_v2, api_v1):
             logging.error("La función post_gif_from_temp_file indicó un fallo.")
             # Considera salir con error para que la Action falle si la publicación no fue exitosa
             # exit(1)
    else:
        logging.error("Fallo en autenticación dual. La publicación no se ejecutó.")
        # Salir con error si la autenticación falla
        exit(1)

# --- Punto de Entrada Principal ---
if __name__ == "__main__":
    logging.info("Iniciando ejecución para GitHub Action...")

    # Verificaciones iniciales
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        logging.error("Error Crítico: Faltan credenciales API en las variables de entorno (Secrets de GitHub).")
        exit(1) # Salir si faltan credenciales
    if not GIF_BASE_URL or TOTAL_GIF_COUNT <= 0:
        logging.error("Error Crítico: GIF_BASE_URL o TOTAL_GIF_COUNT no configurados o inválidos.")
        exit(1) # Salir si falta configuración esencial
    if not os.path.exists(STATE_FILE_PATH):
         logging.error(f"Error Crítico: El archivo de estado '{STATE_FILE_PATH}' no existe en el repositorio.")
         exit(1) # Salir si el archivo de estado no está donde se espera


    # Ejecutar la lógica principal directamente
    job()

    # El log final ahora lo maneja el workflow de Actions
    logging.info("Proceso del script Python finalizado.")
