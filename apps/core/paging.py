"""How lists are cut into pages, in one place. How long a page is belongs to an admin: each client's
in Company settings (apps.org.listing.page_of), the platform's for the console in its settings. The
mobile API's pages are part of its contract, and the JSON API's are the caller's to ask for."""

from django.core.paginator import Paginator

DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_CHOICES = [(size, str(size)) for size in (10, 25, 50, 100)]


def paginate(request, rows, size: int):
    return Paginator(rows, size).get_page(request.GET.get("page"))
