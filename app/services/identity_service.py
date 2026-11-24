import hashlib
from app.models import AnonymityMode  # the enum

# Indonesian animal names for aliases
ANIMAL_NAMES = [
    "Rubah", "Elang", "Harimau", "Kucing", "Kelinci",
    "Singa", "Panda", "Beruang", "Rusa", "Kuda",
    "Serigala", "Lumba-lumba", "Gajah", "Zebra", "Jerapah"
]


def generate_alias(user_id: int) -> str:
    # Use hash to pick animal and number deterministically
    hash_val = int(hashlib.md5(str(user_id).encode()).hexdigest(), 16)
    animal = ANIMAL_NAMES[hash_val % len(ANIMAL_NAMES)]
    number = (hash_val // len(ANIMAL_NAMES)) % 1000
    return f"Anonim {animal} #{number:03d}"


def resolve_display_name(
    author_id: int,
    author_full_name: str,
    author_batch_year: int,
    author_alias: str,
    is_anonymous: bool,
    space_anonymity_mode: str,
    viewer_is_admin: bool = False,
    space_admin_id: int = None,
) -> str:
    """
    Tentukan nama yang ditampilkan berdasarkan mode anonimitas Space.

    - OPEN_ONLY  : selalu nama asli + angkatan
    - ANON_ONLY  : selalu alias, kecuali admin Space
    - USER_CHOICE: ikuti flag is_anonymous per postingan
    """
    real_name = f"{author_full_name} ({author_batch_year})"

    if space_anonymity_mode == AnonymityMode.OPEN_ONLY:
        return real_name

    elif space_anonymity_mode == AnonymityMode.ANON_ONLY:
        # Space admin's own posts are shown with real name
        if author_id == space_admin_id:
            return real_name
        return author_alias

    else:  # USER_CHOICE
        if is_anonymous:
            return author_alias
        return real_name
