import os
import requests
import io
import zipfile_deflate64 as zipfile 

def download_orn_geopackage():
    """Downloads the v2.0 March 2025 GeoPackage zip bundle using Deflate64 decoding."""
    download_url = "https://openrivers.net/download/ORN_v2_GeoPackage.zip"
    
    target_dir = "data/raw"
    os.makedirs(target_dir, exist_ok=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/zip, application/octet-stream"
    }
    
    print("Initiating secure download of the v2.0 GeoPackage archive...")
    
    try:
        response = requests.get(download_url, headers=headers, stream=True, timeout=120)
        response.raise_for_status()
        
        print("Download finished. Extracting GeoPackage via zipfile-deflate64...")
        # ZipFile context block now natively decodes method 9 files seamlessly
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
            zip_ref.extractall(target_dir)
            
        print(f"Extraction successful! Your latest hydrology files are ready inside: {target_dir}")
        
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP Error: The server blocked or couldn't find the link. Code: {http_err}")
    except Exception as err:
        print(f"An unexpected extraction error occurred: {err}")

if __name__ == "__main__":
    download_orn_geopackage()
