"""Protect (AES-256 password + permissions) and Unlock."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QGroupBox, QLineEdit, QVBoxLayout

from pdfsoul.app.jobs import JobSpec
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.widgets import OutputPicker, muted
from pdfsoul.core import secure
from pdfsoul.core.types import PdfSoulError, Result


def _password_edit(placeholder: str) -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText(placeholder)
    return edit


class ProtectPanel(ToolPanel):
    tool_id = "protect"
    title = "Protect PDF"
    blurb = "Encrypt with AES-256. PDFSoul never stores your passwords — keep them safe."
    primary_label = "Protect"

    def build(self) -> None:
        self.password_edit = _password_edit("Needed to open the file")
        self.confirm = _password_edit("Type it again")
        self.form.addRow("Password", self.password_edit)
        self.form.addRow("Confirm", self.confirm)

        self.restrict = QGroupBox("Restrict what people can do")
        self.restrict.setCheckable(True)
        self.restrict.setChecked(False)
        box = QVBoxLayout(self.restrict)
        self.allow_print = QCheckBox("Allow printing")
        self.allow_copy = QCheckBox("Allow copying text and images")
        self.allow_edit = QCheckBox("Allow editing and annotating")
        for check in (self.allow_print, self.allow_copy, self.allow_edit):
            check.setChecked(True)
            box.addWidget(check)
        self.owner = _password_edit("Owner password (to change these later)")
        box.addWidget(self.owner)
        box.addWidget(muted("Leave the main password blank to let anyone open the file "
                            "with these restrictions."))
        self.form.addRow(self.restrict)
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "protected") if path else None

    def document_changed(self) -> None:
        self.output.reset()

    def make_job(self) -> JobSpec:
        user = self.password_edit.text()
        if user != self.confirm.text():
            raise PdfSoulError("The passwords don't match.")
        restrict = self.restrict.isChecked()
        owner = self.owner.text() if restrict else ""
        if not user and not owner:
            raise PdfSoulError("Enter a password (or an owner password under restrictions).")
        output = self.output.path()
        assert output is not None
        return JobSpec("Protecting", secure.protect, [self.source], output,
                       secure.ProtectOptions(
                           user_password=user, owner_password=owner,
                           allow_print=not restrict or self.allow_print.isChecked(),
                           allow_copy=not restrict or self.allow_copy.isChecked(),
                           allow_edit=not restrict or self.allow_edit.isChecked(),
                           current_password=self.password))

    def on_result(self, result: Result) -> None:
        for edit in (self.password_edit, self.confirm, self.owner):
            edit.clear()
        self.output.reset()


class UnlockPanel(ToolPanel):
    tool_id = "unlock"
    title = "Remove password"
    blurb = "Save an unprotected copy. You need to know the password."
    primary_label = "Remove password"

    def build(self) -> None:
        self.state = muted("")
        self.form.addRow(self.state)
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)
        self._encrypted = False

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "unlocked") if path else None

    def document_changed(self) -> None:
        self.output.reset()
        path = self.ctx.session.path
        if path is None:
            return
        perms = secure.permissions(path, self.password)
        self._encrypted = perms.encrypted
        if not perms.encrypted:
            self.state.setText("This file isn't protected.")
        elif self.password:
            self.state.setText("Protected — you unlocked it when opening. "
                               "The copy will open without a password.")
        else:
            self.state.setText("Opens freely but has restrictions (no printing, copying or "
                               "editing). The copy will have none.")

    def can_run(self) -> bool:
        return self._encrypted if hasattr(self, "_encrypted") else False

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Removing password", secure.unlock, [self.source], output,
                       secure.UnlockOptions(password=self.password or ""))

    def on_result(self, result: Result) -> None:
        self.output.reset()
