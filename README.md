# YouTube Audio Downloader

Applicazione desktop per convertire video YouTube in MP3, con supporto a playlist,
download multipli in parallelo e gestione dei cookie.

## Funzionalità

- Conversione di video YouTube in MP3 (192K, migliore traccia audio disponibile)
- Download di intere playlist o di singoli brani
- Più URL incollati insieme, uno per riga
- Due modalità: **Playlist** e **Single Songs**
- Nella modalità **Playlist** puoi incollare insieme playlist e singoli video:
  - le playlist vengono salvate in sottocartelle col nome della playlist
  - i singoli video vengono salvati in una cartella chiamata **NA**
- Download paralleli (12 thread di default)
- Supporto cookie: file di cookie oppure cookie dal browser (Chrome, Firefox, Edge, Opera, Vivaldi, Brave)
- Tema scuro/chiaro
- Modalità Debug per vedere l'output completo di yt-dlp in caso di errori
- Aggiornamento automatico di yt-dlp: una copia è inclusa nell'exe e viene
  aggiornata da GitHub se disponibile una versione più recente
- Singolo file .exe portatile: Python, FFmpeg, FFprobe e yt-dlp sono tutti inclusi
- Scelta della cartella di salvataggio

## Utilizzo

1. Incolla uno o più URL YouTube (uno per riga)
2. Scegli la modalità **Playlist** o **Single Songs**
3. (Opzionale) Seleziona un browser o un file di cookie per i contenuti protetti
4. Premi **START DOWNLOAD**
5. I file MP3 vengono salvati nella cartella scelta (default: `Desktop\downloaded_music`)

Nella modalità **Playlist** puoi mischiare playlist e singoli video. I singoli
video (quelli che non appartengono a una playlist) vengono salvati in una
sottocartella chiamata **NA**: è il valore che yt-dlp usa quando un campo
come il nome della playlist non è disponibile.

## Scaricare l'eseguibile

L'ultima versione compilata è disponibile nella sezione **Releases**:
è un singolo file portatile (`YouTubeDownloader2.0.exe`), senza installazione.

## Compilare da sorgente

Prerequisiti: Python 3 (testato con 3.13).

1. Clona il repository e installa le dipendenze:

   ```bash
   pip install -r requirements.txt
   ```

2. Scarica e metti questi tre file nella cartella `resources`:

   ```
   resources/
   ├── ffmpeg.exe
   ├── ffprobe.exe
   └── yt-dlp.exe
   ```

   - **FFmpeg / FFprobe**: build completa per Windows da
     https://github.com/BtbN/FFmpeg-Builds (release tag `latest`, build `win64-gpl`,
     basta estrarre `bin\ffmpeg.exe` e `bin\ffprobe.exe`)
   - **yt-dlp.exe**: da https://github.com/yt-dlp/yt-dlp/releases

3. Compila l'eseguibile (tutto viene incluso nel file: Python, FFmpeg, FFprobe, yt-dlp):

   ```bash
   pyinstaller --clean YouTubeDownloader2.0.spec
   ```

4. L'eseguibile si trova in `dist\YouTubeDownloader2.0.exe`

### Eseguire senza compilare

Per provare l'app direttamente dal sorgente:

```bash
python youtube_audio_downloader_gui.py
```

In questo caso `yt-dlp` deve essere raggiungibile dal PATH, e FFmpeg nella
cartella `resources` accanto allo script.

## Consigli

- **max_workers**: in `youtube_audio_downloader_gui.py`, nel metodo
  `run_download_logic`, è impostato `ThreadPoolExecutor(max_workers=12)`.
  Questo numero decide quanti download avvengono in parallelo: **abbassalo su
  PC con poca RAM o CPU, alzalo su PC più potenti** (ad esempio 4 su PC
  modesti, 20+ su PC performanti).
- Se un download fallisce, attiva **Debug Mode** per vedere l'output completo
  di yt-dlp.
- Per contenuti con limiti d'età, usa i cookie del browser o un file di cookie.
- L'app salva un backup degli URL in `~\.yt-audio-downloader\saved_urls.txt`
  e tiene aggiornato yt-dlp nella stessa cartella.

## Note

- I file binari (ffmpeg, ffprobe, yt-dlp) non sono inclusi nel repository
  perché troppo grandi per GitHub: scaricarli e metterli in `resources` prima
  di compilare.
