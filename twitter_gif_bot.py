import tweepy
import time
import os
import requests
# from dotenv import load_dotenv # No necesario para Actions
import logging
import tempfile # Para crear archivos temporales

# --- Configuración ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# load_dotenv() # No necesario para Actions

# Leer credenciales desde variables de entorno (proporcionadas por GitHub Actions Secrets)
API_KEY = os.getenv("TWITTER_API_KEY")
API_SECRET = os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# --- Configuración del Repositorio de GIFs ---
GIF_BASE_URL = "https://raw.githubusercontent.com/GoonLibrary/GifGallery/main/"
TOTAL_GIF_COUNT = 111 # Asegúrate de que este es el número correcto
STATE_FILE_PATH = "state/next_gif_index.txt" # Ruta relativa para Actions

# --- Funciones Auxiliares ---
def read_next_index():
    """Lee el índice (0-based) del próximo GIF desde el archivo de estado."""
    try:
        if os.path.exists(STATE_FILE_PATH):
            with open(STATE_FILE_PATH, 'r') as f:
                content = f.read().strip()
                logging.info(f"Índice leído de '{STATE_FILE_PATH}': '{content}'")
                return int(content) if content.isdigit() else 0
        else:
            logging.warning(f"Archivo de estado '{STATE_FILE_PATH}' no encontrado! Empezando desde 0.")
            return 0
    except (ValueError, IOError) as e:
        logging.error(f"Error leyendo '{STATE_FILE_PATH}': {e}. Empezando desde 0.")
        return 0
    except Exception as e:
        logging.error(f"Error inesperado leyendo índice: {e}. Empezando desde 0.")
        return 0

def write_next_index(index):
    """Escribe el índice (0-based) en el archivo de estado."""
    try:
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
        if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
            logging.error("Credenciales API no definidas en env vars.")
            return None, None
        client_v2 = tweepy.Client(consumer_key=API_KEY, consumer_secret=API_SECRET, access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET, wait_on_rate_limit=True)
        auth_v1 = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
        api_v1 = tweepy.API(auth_v1, wait_on_rate_limit=True)
        user = api_v1.verify_credentials()
        logging.info(f"Autenticación OK (Usuario: {user.screen_name}).")
        return client_v2, api_v1
    except tweepy.errors.TweepyException as e:
        logging.error(f"Error de autenticación: {e}")
        return None, None
    except Exception as e:
        logging.error(f"Error inesperado autenticación: {e}", exc_info=True)
        return None, None

# --- Función Principal (Descarga a Temp, Subida v1, Espera 30s, Publicación v2 con Hashtags Originales) ---
def post_gif_from_temp_file(client_v2, api_v1):
    """Descarga GIF (X.gif) a temp, sube (v1), espera 30s, publica (v2) con hashtags originales."""
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
            logging.error(f"Error descarga ({selected_gif_url}): {e}. ¿Archivo {gif_filename} existe?"); return False

        fd, temp_gif_path = tempfile.mkstemp(suffix=".gif")
        logging.info(f"Creando archivo temporal: {temp_gif_path}")
        with os.fdopen(fd, 'wb') as temp_file: temp_file.write(gif_content)
        logging.info(f"GIF guardado temporalmente en: {temp_gif_path}")

        logging.info(f"Subiendo GIF desde archivo temporal {temp_gif_path} (v1.1)...")
        # Quitar media_category para simplificar, puede que no sea necesaria con este método
        media = api_v1.media_upload(filename=temp_gif_path)
        media_id = media.media_id_string
        if not media_id:
             logging.error("Fallo crítico: No Media ID tras subida.");
             if temp_gif_path and os.path.exists(temp_gif_path): os.remove(temp_gif_path)
             return False
        logging.info(f"GIF subido desde archivo. Media ID: {media_id}")

        # --- Volver a la espera de 30 segundos ---
        wait_time = 30
        logging.info(f"Esperando {wait_time} segundos antes de publicar con v2...")
        time.sleep(wait_time)

        logging.info(f"Publicando tweet (v2) con Media ID: {media_id} y hashtags originales...")
        if media_id:
            # --- ¡CAMBIO AQUÍ! Hashtags originales ---
            tweet_text = "#GOON #GOONER #GOONETTE #PORN #CNC #FREEUSE #GOONED"
            tweet_response = client_v2.create_tweet(text=tweet_text, media_ids=[media_id])
            logging.info(f"Tweet publicado (v2)! ID: {tweet_response.data['id']}")
            next_index = (current_index + 1) % TOTAL_GIF_COUNT
            write_next_index(next_index)
            success = True
        else: logging.error("Error crítico: Media ID nulo antes de publicar."); return False

    except tweepy.errors.TweepyException as e:
        error_msg = f"Error de Tweepy durante publicación v2 (Media ID: {media_id}): {e}"
        logging.error(error_msg) # Aquí podría volver el error 400 si el GIF #8 era el problema
        return False
    except Exception as e:
        logging.error(f"Error inesperado: {e}", exc_info=True)
        return False
    finally:
        if temp_gif_path and os.path.exists(temp_gif_path):
            try: os.remove(temp_gif_path); logging.info(f"Archivo temporal {temp_gif_path} eliminado.")
            except OSError as e: logging.error(f"Error al eliminar {temp_gif_path}: {e}")

    return success

# --- Función Job ---
def job():
    logging.info("Ejecutando tarea: Descarga (X.gif) a temp, Subir (v1), esperar 30s, publicar (v2) con hashtags originales.")
    client_v2, api_v1 = authenticate_twitter()
    if client_v2 and api_v1:
        if not post_gif_from_temp_file(client_v2, api_v1):
             logging.error("La función post_gif_from_temp_file indicó un fallo.")
             # exit(1) # Opcional: hacer fallar la Action
    else:
        logging.error("Fallo en autenticación dual.")
        exit(1)

# --- Punto de Entrada Principal ---
if __name__ == "__main__":
    logging.info("Iniciando ejecución única (Descarga a temp, Nombre X.gif, Espera 30s, Hashtags Originales)...")
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]): logging.error("Error Crítico: Credenciales API."); exit(1)
    if not GIF_BASE_URL or TOTAL_GIF_COUNT <= 0: logging.error("Error Crítico: GIF_BASE_URL o TOTAL_GIF_COUNT."); exit(1)
    if not os.path.exists(STATE_FILE_PATH): logging.error(f"Error Crítico: '{STATE_FILE_PATH}' no existe."); exit(1)
    job()
    logging.info("Proceso del script Python finalizado.")
