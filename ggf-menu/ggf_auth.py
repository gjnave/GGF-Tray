"""
GGF Patreon Authentication Manager - Token Based
Simple, reliable auth without browser cookie access
"""
import json
import os
import time
import urllib.request
import urllib.error
import webbrowser
import secrets
from datetime import datetime, timedelta
from ggf_runtime import configure_ssl_environment, urlopen_with_ssl

configure_ssl_environment()

class AuthManager:
    def __init__(self, cache_file="auth_cache.json"):
        self.cache_file = cache_file
        self.verify_url = "https://getgoingfast.pro/app-auth-check.php"
        self.login_url = "https://getgoingfast.pro/patreon-login.php"
        self.cached_auth = None
        self.load_cache()
    
    def load_cache(self):
        """Load cached auth from disk"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self.cached_auth = json.load(f)
                    # Check if expired
                    if self.cached_auth.get('expires', 0) < time.time():
                        print("Cached auth expired")
                        self.cached_auth = None
            except Exception as e:
                print(f"Error loading auth cache: {e}")
                self.cached_auth = None
    
    def save_cache(self, auth_data):
        """Save auth to disk cache"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(auth_data, f, indent=2)
            self.cached_auth = auth_data
        except Exception as e:
            print(f"Error saving auth cache: {e}")
    
    def clear_cache(self):
        """Clear cached auth"""
        self.cached_auth = None
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except:
                pass
    
    def generate_token(self):
        """Generate a unique auth token"""
        return f"ggf_tray_{secrets.token_urlsafe(32)}"
    
    def check_token(self, token):
        """
        Check if token has been validated on server
        Returns auth data dict or None
        """
        try:
            url = f"{self.verify_url}?token={token}"
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'GGF-Tray-App/1.0')
            
            with urlopen_with_ssl(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('authenticated'):
                    auth_data = {
                        'tier': data.get('tier', 'free'),
                        'name': data.get('name', 'User'),
                        'expires': time.time() + (14 * 24 * 60 * 60),  # 2 weeks
                        'token': token,
                        'verified_at': time.time()
                    }
                    return auth_data
                else:
                    return None
                    
        except urllib.error.URLError as e:
            # Server unreachable - not an error, just not validated yet
            return None
        except Exception as e:
            print(f"Error checking token: {e}")
            return None
    
    def get_auth(self, force_refresh=False):
        """
        Get current authentication state
        Returns: {tier, name, expires} or None
        """
        # If we have valid cached auth and not forcing refresh, use it
        if not force_refresh and self.cached_auth:
            # Check if expired
            if self.cached_auth.get('expires', 0) > time.time():
                # Re-verify every hour to catch revoked access
                if self.cached_auth.get('verified_at', 0) > time.time() - 3600:
                    return self.cached_auth
                
                # Try to re-verify with token
                token = self.cached_auth.get('token')
                if token:
                    auth_data = self.check_token(token)
                    if auth_data:
                        self.save_cache(auth_data)
                        return auth_data
        
        return None
    
    def login(self):
        """
        Start login flow - generates token and opens browser
        Returns the token for polling
        """
        token = self.generate_token()
        login_url = f"{self.login_url}?app=tray&app_token={token}"
        
        print("=" * 60)
        print("Opening browser for Patreon login...")
        print(f"Token: {token}")
        print("=" * 60)
        
        webbrowser.open(login_url)
        return token
    
    def poll_for_auth(self, token, timeout=300, interval=2):
        """
        Poll server to check if token has been validated
        Returns auth data when validated or None on timeout
        
        timeout: seconds to wait (default 5 minutes)
        interval: seconds between checks (default 2 seconds)
        """
        start_time = time.time()
        attempts = 0
        
        print("Waiting for Patreon login...")
        
        while time.time() - start_time < timeout:
            attempts += 1
            auth_data = self.check_token(token)
            
            if auth_data:
                print(f"\n✓ Login successful!")
                print(f"  Name: {auth_data['name']}")
                print(f"  Tier: {auth_data['tier']}")
                self.save_cache(auth_data)
                return auth_data
            
            # Show progress every 10 attempts
            if attempts % 10 == 0:
                elapsed = int(time.time() - start_time)
                print(f"  Still waiting... ({elapsed}s)")
            
            time.sleep(interval)
        
        print("\n✗ Login timeout - please try again")
        return None
    
    def get_tier(self):
        """Get user's tier (free/prairie-dog/premium)"""
        auth = self.get_auth()
        return auth['tier'] if auth else 'free'
    
    def get_name(self):
        """Get user's name"""
        auth = self.get_auth()
        return auth['name'] if auth else None
    
    def is_authenticated(self):
        """Check if user is authenticated"""
        return self.get_auth() is not None
    
    def has_tier_access(self, required_tier):
        """
        Check if user has access to a specific tier
        Tier hierarchy: premium > prairie-dog > free
        """
        user_tier = self.get_tier()
        
        tier_levels = {
            'free': 0,
            'prairie-dog': 1,
            'premium': 2
        }
        
        return tier_levels.get(user_tier, 0) >= tier_levels.get(required_tier, 0)
    
    def format_tier_name(self, tier=None):
        """Format tier name for display"""
        if tier is None:
            tier = self.get_tier()
        
        tier_names = {
            'free': 'Free',
            'prairie-dog': 'Prairie Dog',
            'farm-hand': 'Farm Hand',
            'rancher': 'Rancher',
            'gunslinger': 'Gunslinger'
        }
        
        return tier_names.get(tier, tier.title())

if __name__ == "__main__":
    # Test the auth manager
    auth = AuthManager()
    
    print("=" * 50)
    print("GGF Auth Manager Test")
    print("=" * 50)
    
    if auth.is_authenticated():
        print(f"✓ Authenticated as: {auth.get_name()}")
        print(f"  Tier: {auth.format_tier_name()}")
        print(f"  Has prairie-dog access: {auth.has_tier_access('prairie-dog')}")
        print(f"  Has premium access: {auth.has_tier_access('premium')}")
    else:
        print("✗ Not authenticated")
        print("\nStarting login flow...")
        token = auth.login()
        print(f"\nPolling for authentication...")
        result = auth.poll_for_auth(token)
        
        if result:
            print("\n✓ Successfully authenticated!")
        else:
            print("\n✗ Authentication failed or timed out")
