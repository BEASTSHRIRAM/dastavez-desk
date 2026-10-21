"""Where a template's .docx lives: bundled files for built-ins, tenant storage for a business's own."""
from pathlib import Path

from app.models.orm import TemplateVersion
from app.services import storage
from app.templates.builder import template_file


def template_path(tv: TemplateVersion) -> Path:
    if tv.tenant_id is None:
        return template_file(tv.template_key, tv.version)
    return storage.resolve(tv.tenant_id, "templates", tv.file_name)
