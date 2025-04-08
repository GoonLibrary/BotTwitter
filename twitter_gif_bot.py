import tweepy
import time
import os
import requests
from dotenv import load_dotenv
import logging
import tempfile # Para crear archivos temporales

# --- Configuración ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

API_KEY = os.getenv("TWITTER_API_KEY")
API_SECRET = os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# --- Configuración del Repositorio de GIFs ---
GIF_BASE_URL = "https://raw.githubusercontent.com/GoonLibrary/GifGallery/main/"
TOTAL_GIF_COUNT = 111 # Asegúrate de que este es el número correcto
STATE_FILE = "next_gif_index.txt"

# --- Funciones Auxiliares ---
def read_next_index():
    """Lee el índice (0-based) del próximo GIF desde el archivo de estado."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f: content = f.read().strip(); return int(content) if content else 0
        else: logging.info(f"'{STATE_FILE}' no encontrado. Empezando desde 0."); return 0
    except (ValueError, IOError) as e: logging.error(f"Error leyendo '{STATE_FILE}': {e}. Empezando desde 0."); return 0

def write_next_index(index):
    """Escribe el índice (0-based) del próximo GIF en el archivo de estado."""
    try:
        with open(STATE_FILE, 'w') as f: f.write(str(index)); logging.info(f"Próximo índice ({index}) guardado en '{STATE_FILE}'.")
    except IOError as e: logging.error(f"Error escribiendo en '{STATE_FILE}': {e}")

def authenticate_twitter():
    """Autentica con Twitter API v1.1 y v2."""
    try:
        client_v2 = tweepy.Client(consumer_key=API_KEY, consumer_secret=API_SECRET, access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET, wait_on_rate_limit=True)
        auth_v1 = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
        api_v1 = tweepy.API(auth_v1, wait_on_rate_limit=True)
        api_v1.verify_credentials()
        logging.info("Autenticación Twitter v1.1 y v2 OK.")
        return client_v2, api_v1
    except tweepy.errors.TweepyException as e: logging.error(f"Error de autenticación: {e}"); return None, None
    except Exception as e: logging.error(f"Error inesperado autenticación: {e}", exc_info=True); return None, None

# --- Función Principal (Descarga a Temp, Sin Cat, Espera 30s, Publica con Hashtags) ---
def post_gif_from_temp_file(client_v2, api_v1):
    """Descarga GIF a temp, sube (v1), espera 30s, publica (v2) CON HASHTAGS."""
    if not client_v2 or not api_v1: logging.error("Clientes API no inicializados."); return False
    if not GIF_BASE_URL or TOTAL_GIF_COUNT <= 0: logging.error("Error config GIF_BASE_URL/TOTAL_GIF_COUNT."); return False

    media_id = None
    success = False
    temp_gif_path = None

    try:
        current_index = read_next_index()
        if current_index < 0 or current_index >= TOTAL_GIF_COUNT: logging.warning(f"Índice {current_index} fuera rango. Reiniciando."); current_index = 0

        gif_number = current_index + 1
        gif_filename = f"{gif_number}.gif"
        selected_gif_url = GIF_BASE_URL.strip('/') + '/' + gif_filename
        logging.info(f"Índice: {current_index}. Intentando con GIF #{gif_number} desde: {selected_gif_url}")

        logging.info(f"Descargando GIF: {selected_gif_url}...")
        try:
            response = requests.get(selected_gif_url, timeout=90)
            response.raise_for_status()
            gif_content = response.content
            logging.info(f"Descarga completa. Tamaño: {len(gif_content)} bytes.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error descarga ({selected_gif_url}): {e}. ¿Archivo existe?"); return False

        # --- Guardar en archivo temporal ---
        fd, temp_gif_path = tempfile.mkstemp(suffix=".gif")
        logging.info(f"Creando archivo temporal: {temp_gif_path}")
        with os.fdopen(fd, 'wb') as temp_file: temp_file.write(gif_content)
        logging.info(f"GIF guardado temporalmente en: {temp_gif_path}")

        # --- Subir DESDE el archivo temporal (SIN media_category explícita) ---
        logging.info(f"Subiendo GIF desde archivo temporal {temp_gif_path} (v1.1, sin categoría explícita)...")
        media = api_v1.media_upload(filename=temp_gif_path)
        media_id = media.media_id_string
        if not media_id:
             logging.error("Fallo crítico: No Media ID tras subida desde archivo.")
             if temp_gif_path and os.path.exists(temp_gif_path): os.remove(temp_gif_path)
             return False
        logging.info(f"GIF subido desde archivo. Media ID: {media_id}")

        # --- Espera de 30 segundos ---
        wait_time = 30 # Mantener 30 segundos que funcionó
        logging.info(f"Esperando {wait_time} segundos antes de publicar con v2...")
        time.sleep(wait_time)

        # --- Publicar Tweet (API v2) CON HASHTAGS ---
        logging.info(f"Publicando tweet (v2) con Media ID: {media_id} y hashtags...")
        if media_id:
            # --- ¡CAMBIO AQUÍ! Texto del tweet actualizado ---
            tweet_text = "#GOON #GOONER #GOONETTE #PORN #CNC #FREEUSE #GOONED"
            tweet_response = client_v2.create_tweet(
                text=tweet_text,
                media_ids=[media_id]
            )
            logging.info(f"Tweet publicado (v2)! ID: {tweet_response.data['id']}")
            next_index = (current_index + 1) % TOTAL_GIF_COUNT
            write_next_index(next_index)
            success = True
        else:
             logging.error("Error crítico: Media ID se volvió nulo antes de publicar.")
             return False

    except tweepy.errors.TweepyException as e:
        error_msg = f"Error de Tweepy durante publicación v2 (Media ID: {media_id}): {e}"
        logging.error(error_msg)
        return False
    except Exception as e:
        logging.error(f"Error inesperado: {e}", exc_info=True)
        return False
    finally:
        # --- Asegurarse de eliminar el archivo temporal ---
        if temp_gif_path and os.path.exists(temp_gif_path):
            try: os.remove(temp_gif_path); logging.info(f"Archivo temporal {temp_gif_path} eliminado.")
            except OSError as e: logging.error(f"Error al eliminar {temp_gif_path}: {e}")

    return success

# --- Función Job ---
def job():
    # (Sin cambios)
    logging.info("Ejecutando tarea: Descarga (X.gif) a temp, Subir (v1), esperar 30s, publicar (v2) con hashtags.")
    client_v2, api_v1 = authenticate_twitter()
    if client_v2 and api_v1: post_gif_from_temp_file(client_v2, api_v1)
    else: logging.error("Fallo en autenticación dual.")

# --- Punto de Entrada Principal ---
if __name__ == "__main__":
    # (Sin cambios)
    logging.info("Iniciando ejecución única (Descarga a temp, Nombre X.gif, Hashtags, Sin Cat, Espera 30s)...")
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]): logging.error("Error Crítico: Credenciales API."); exit(1)
    if not GIF_BASE_URL or TOTAL_GIF_COUNT <= 0: logging.error("Error Crítico: GIF_BASE_URL o TOTAL_GIF_COUNT."); exit(1)
    job()
    logging.info("Ejecución única (Descarga a temp, Nombre X.gif, Hashtags, Sin Cat, Espera 30s) completada.")