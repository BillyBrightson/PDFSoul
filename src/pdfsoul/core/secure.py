"""Password protection (AES-256), unlocking, and permissions. Passwords are never stored."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pikepdf

from pdfsoul.core.safe_io import atomic_output
from pdfsoul.core.types import (
    PasswordRequired,
    PdfSoulError,
    ProgressFn,
    Result,
    WrongPassword,
    no_progress,
)


@dataclass
class ProtectOptions:
    user_password: str = ""  # needed to open the file; blank = opens freely, permissions apply
    owner_password: str = ""  # needed to change permissions; blank = same as user password
    allow_print: bool = True
    allow_copy: bool = True
    allow_edit: bool = True
    current_password: str | None = None  # if the input is already encrypted


def protect(inputs: list[Path], output: Path, opts: ProtectOptions,
            progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    if not opts.user_password and not opts.owner_password:
        raise PdfSoulError("Enter a password.")
    owner = opts.owner_password or opts.user_password
    allow = pikepdf.Permissions(
        print_lowres=opts.allow_print,
        print_highres=opts.allow_print,
        extract=opts.allow_copy,
        accessibility=True,
        modify_annotation=opts.allow_edit,
        modify_assembly=opts.allow_edit,
        modify_form=opts.allow_edit,
        modify_other=opts.allow_edit,
    )
    with _open(Path(inputs[0]), opts.current_password) as pdf:
        progress(0.5)
        with atomic_output(Path(output)) as tmp:
            pdf.save(tmp, encryption=pikepdf.Encryption(
                user=opts.user_password, owner=owner, R=6, aes=True, allow=allow))
    progress(1.0)
    what = "Password protected" if opts.user_password else "Permissions restricted"
    return Result([Path(output)], f"{what} with AES-256.")


@dataclass
class UnlockOptions:
    password: str = ""


def unlock(inputs: list[Path], output: Path, opts: UnlockOptions,
           progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Remove the password and all restrictions (the password must be known)."""
    source = Path(inputs[0])
    with _open(source, opts.password) as pdf:
        if not pdf.is_encrypted:
            raise PdfSoulError(f"{source.name} isn't password protected.")
        progress(0.5)
        with atomic_output(Path(output)) as tmp:
            pdf.save(tmp)  # pikepdf drops encryption unless asked to keep it
    progress(1.0)
    return Result([Path(output)], "Password removed.")


@dataclass
class Permissions:
    encrypted: bool
    needs_password: bool
    print: bool
    copy: bool
    edit: bool


def permissions(path: Path, password: str | None = None) -> Permissions:
    try:
        with pikepdf.open(path, password=password or "") as pdf:
            allow = pdf.allow
            return Permissions(
                encrypted=pdf.is_encrypted,
                needs_password=False,
                print=bool(allow.print_highres or allow.print_lowres),
                copy=bool(allow.extract),
                edit=bool(allow.modify_other),
            )
    except pikepdf.PasswordError:
        return Permissions(True, True, False, False, False)


def _open(path: Path, password: str | None) -> pikepdf.Pdf:
    try:
        return pikepdf.open(path, password=password or "", attempt_recovery=True)
    except pikepdf.PasswordError as exc:
        if password:
            raise WrongPassword(f"Wrong password for {path.name}.") from exc
        raise PasswordRequired(f"{path.name} is password protected.") from exc
    except FileNotFoundError as exc:
        raise PdfSoulError(f"File not found: {path}") from exc
    except pikepdf.PdfError as exc:
        raise PdfSoulError(f"Couldn't read {path.name}: {exc}") from exc
