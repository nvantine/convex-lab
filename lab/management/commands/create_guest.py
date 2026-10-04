"""Create a nonstaff guest; store generated credentials in an ignored private file."""
import secrets
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the guest login. Password is written privately to .local/guest-login.txt."

    def handle(self, *args, **options):
        user_model = get_user_model()
        if user_model.objects.filter(username=settings.GUEST_USERNAME).exists():
            self.stdout.write("Guest already exists; no password was changed.")
            return
        local = settings.BASE_DIR / ".local"
        local.mkdir(exist_ok=True, mode=0o700)
        target = local / "guest-login.txt"
        if target.exists():
            raise CommandError("Guest credential file already exists; review it before creating another login.")
        password = secrets.token_urlsafe(18)
        with target.open("x") as stream:
            target.chmod(0o600)
            stream.write(f"Username: {settings.GUEST_USERNAME}\nPassword: {password}\n")
        try:
            user_model.objects.create_user(username=settings.GUEST_USERNAME, password=password)
        except Exception:
            target.unlink()
            raise
        self.stdout.write("Guest created. Login details are in .local/guest-login.txt (not printed or committed).")
