"""
Browser Cookie Reader for Windows
Extracts cookies from Chrome, Edge, and Firefox
"""
import os
import sqlite3
import json
import base64
import tempfile
import shutil
from pathlib import Path

# Windows-specific imports for Chrome decryption
try:
    import win32crypt
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("Warning: win32crypt not available - Chrome cookie decryption will fail")

def get_chrome_cookie(domain, cookie_name):
    """Get cookie from Chrome"""
    if not HAS_WIN32:
        print("  Chrome: Skipped (pywin32 not installed)")
        return None
    
    # Chrome cookie database location
    local_app_data = os.getenv('LOCALAPPDATA')
    chrome_path = os.path.join(local_app_data, 'Google', 'Chrome', 'User Data', 'Default', 'Network', 'Cookies')
    
    print(f"  Chrome: Checking {chrome_path}")
    if not os.path.exists(chrome_path):
        print(f"  Chrome: Cookie database not found")
        return None
    
    print(f"  Chrome: Database exists, attempting to read...")
    return _read_chrome_cookie(chrome_path, domain, cookie_name)

def get_edge_cookie(domain, cookie_name):
    """Get cookie from Edge"""
    if not HAS_WIN32:
        print("  Edge: Skipped (pywin32 not installed)")
        return None
    
    # Edge cookie database location
    local_app_data = os.getenv('LOCALAPPDATA')
    edge_path = os.path.join(local_app_data, 'Microsoft', 'Edge', 'User Data', 'Default', 'Network', 'Cookies')
    
    print(f"  Edge: Checking {edge_path}")
    if not os.path.exists(edge_path):
        print(f"  Edge: Cookie database not found")
        return None
    
    print(f"  Edge: Database exists, attempting to read...")
    return _read_chrome_cookie(edge_path, domain, cookie_name)

def _read_chrome_cookie(db_path, domain, cookie_name):
    """Read cookie from Chrome/Edge SQLite database"""
    try:
        print(f"    Copying database to temp...")
        # Copy database to temp location (Chrome locks the file)
        temp_db = os.path.join(tempfile.gettempdir(), 'temp_cookies.db')
        shutil.copy2(db_path, temp_db)
        
        print(f"    Querying for cookie: {cookie_name} on domain: {domain}")
        # Connect to database
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # Query for the cookie
        cursor.execute(
            "SELECT name, encrypted_value, host_key FROM cookies WHERE host_key LIKE ? AND name = ?",
            (f'%{domain}%', cookie_name)
        )
        
        result = cursor.fetchone()
        conn.close()
        
        # Clean up temp file
        try:
            os.remove(temp_db)
        except:
            pass
        
        if not result:
            print(f"    No cookie found in database")
            # Try to see what cookies ARE there
            conn = sqlite3.connect(temp_db) if os.path.exists(temp_db) else sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT host_key FROM cookies WHERE host_key LIKE '%getgoingfast%'")
            hosts = cursor.fetchall()
            conn.close()
            if hosts:
                print(f"    Found these getgoingfast domains: {[h[0] for h in hosts]}")
            else:
                print(f"    No getgoingfast cookies found at all")
            return None
        
        name, encrypted_value, host = result
        print(f"    Found cookie on host: {host}")
        print(f"    Decrypting...")
        
        # Decrypt the cookie value
        decrypted_value = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode('utf-8')
        
        print(f"    ✓ Successfully decrypted!")
        return decrypted_value
        
    except Exception as e:
        print(f"    ✗ Error reading Chrome/Edge cookie: {e}")
        return None

def get_firefox_cookie(domain, cookie_name):
    """Get cookie from Firefox"""
    try:
        # Firefox profile directory
        app_data = os.getenv('APPDATA')
        firefox_base = os.path.join(app_data, 'Mozilla', 'Firefox', 'Profiles')
        
        if not os.path.exists(firefox_base):
            return None
        
        # Find default profile (usually ends with .default-release)
        profiles = [p for p in os.listdir(firefox_base) if os.path.isdir(os.path.join(firefox_base, p))]
        if not profiles:
            return None
        
        # Try each profile
        for profile in profiles:
            cookies_db = os.path.join(firefox_base, profile, 'cookies.sqlite')
            if not os.path.exists(cookies_db):
                continue
            
            try:
                # Copy to temp (Firefox may lock the file)
                temp_db = os.path.join(tempfile.gettempdir(), 'temp_ff_cookies.db')
                shutil.copy2(cookies_db, temp_db)
                
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT name, value FROM moz_cookies WHERE host LIKE ? AND name = ?",
                    (f'%{domain}%', cookie_name)
                )
                
                result = cursor.fetchone()
                conn.close()
                
                # Clean up
                try:
                    os.remove(temp_db)
                except:
                    pass
                
                if result:
                    return result[1]  # Return cookie value
                    
            except Exception as e:
                print(f"Error reading Firefox cookie from {profile}: {e}")
                continue
        
        return None
        
    except Exception as e:
        print(f"Error accessing Firefox cookies: {e}")
        return None

def get_cookie_from_any_browser(domain, cookie_name):
    """
    Try to get cookie from any installed browser
    Returns (cookie_value, browser_name) or (None, None)
    """
    # Try Chrome first (most common)
    cookie = get_chrome_cookie(domain, cookie_name)
    if cookie:
        return (cookie, "Chrome")
    
    # Try Edge
    cookie = get_edge_cookie(domain, cookie_name)
    if cookie:
        return (cookie, "Edge")
    
    # Try Firefox
    cookie = get_firefox_cookie(domain, cookie_name)
    if cookie:
        return (cookie, "Firefox")
    
    return (None, None)

if __name__ == "__main__":
    # Test
    cookie, browser = get_cookie_from_any_browser("getgoingfast.pro", "ggf_auth")
    if cookie:
        print(f"Found ggf_auth cookie in {browser}")
        print(f"Value: {cookie[:50]}..." if len(cookie) > 50 else f"Value: {cookie}")
    else:
        print("Cookie not found in any browser")
