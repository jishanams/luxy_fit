import os
import time
import base64
import mimetypes
import threading
import requests
from urllib.parse import urlparse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.conf import settings
# from .models import Product


# In-memory job store (simple, resets on server restart)
_jobs = {}


def health(request):
    return JsonResponse({'ok': True})


def product_detail(request):
    """Returns the first active product so the frontend can display it."""
    product = Product.objects.filter(is_active=True).first()
    if not product:
        return JsonResponse({'error': 'No active product found'}, status=404)
    return JsonResponse({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'category': product.category,
        'brand': product.brand,
        'garment_image_url': request.build_absolute_uri(product.garment_image.url),
    })


def index(request):
    return render(request, 'luxytrends-product-page.html')


def _read_as_base64(url):
    """
    If URL is localhost, read from disk. Otherwise download it.
    Returns a base64 data URI string.
    """
    local_prefixes = ('http://127.0.0.1', 'http://localhost',
                      'https://127.0.0.1', 'https://localhost')
    if url.startswith(local_prefixes):
        parsed = urlparse(url)
        rel_path = parsed.path.lstrip('/')
        local_path = os.path.join(settings.BASE_DIR, rel_path.replace('/', os.sep))
        if not os.path.exists(local_path):
            raise FileNotFoundError(f'Local file not found: {local_path}')
        mime, _ = mimetypes.guess_type(local_path)
        mime = mime or 'image/jpeg'
        with open(local_path, 'rb') as f:
            data = f.read()
    else:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        mime = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        data = resp.content

    b64 = base64.b64encode(data).decode('utf-8')
    return f"data:{mime};base64,{b64}"


def _run_fashn_job(job_id, fashn_api_key, model_b64, garment_b64):
    """Runs in a background thread — calls Fashn and updates job store."""
    _jobs[job_id]['status'] = 'processing'
    base_url = "https://api.fashn.ai/v1"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {fashn_api_key}"
    }
    input_data = {
        "model_name": "tryon-v1.6",
        "inputs": {
            "model_image": model_b64,
            "garment_image": garment_b64,
            "category": "auto"
        }
    }
    try:
        run_resp = requests.post(f"{base_url}/run", json=input_data, headers=headers, timeout=30)
        run_resp.raise_for_status()
        prediction_id = run_resp.json().get("id")
        if not prediction_id:
            _jobs[job_id] = {'status': 'failed', 'error': 'No prediction ID returned'}
            return

        # Poll for completion
        for _ in range(120):  # up to 4 minutes
            time.sleep(2)
            status_resp = requests.get(f"{base_url}/status/{prediction_id}", headers=headers, timeout=15)
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status")

            if status == "completed":
                output = status_data.get("output", [])
                image_url = output[0] if isinstance(output, list) and output else output
                _jobs[job_id] = {
                    'status': 'completed',
                    'result_url': image_url,
                    'prediction_id': prediction_id,
                    'credits_used': status_data.get('creditsUsed'),
                }
                return
            elif status == "failed":
                err = status_data.get('error') or {}
                _jobs[job_id] = {'status': 'failed', 'error': err.get('message', 'FASHN generation failed')}
                return

        _jobs[job_id] = {'status': 'failed', 'error': 'Timed out waiting for Fashn'}
    except Exception as e:
        _jobs[job_id] = {'status': 'failed', 'error': str(e)}


@csrf_exempt
def try_on(request):
    """Start a background try-on job and return a job_id immediately."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)

    fashn_api_key = os.environ.get('FASHN_API_KEY', '').strip()
    if not fashn_api_key or fashn_api_key == 'paste_your_fashn_api_key_here':
        return JsonResponse({'error': 'FASHN_API_KEY is not configured.'}, status=500)

    model_image = request.FILES.get('model_image')
    if not model_image:
        return JsonResponse({'error': 'model_image file is required'}, status=400)

    garment_image_url = request.POST.get('garment_image_url') or os.environ.get('PRODUCT_GARMENT_IMAGE_URL', '')
    if not garment_image_url:
        return JsonResponse({'error': 'garment_image_url is required.'}, status=400)

    try:
        # Convert model image to base64
        image_bytes = model_image.read()
        mime_type = model_image.content_type or 'image/jpeg'
        model_b64 = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"

        # Convert garment image to base64 (reads from disk if localhost URL)
        garment_b64 = _read_as_base64(garment_image_url)
    except Exception as e:
        return JsonResponse({'error': f'Failed to process images: {str(e)}'}, status=400)

    # Create a job ID and start background thread
    job_id = f"job_{int(time.time() * 1000)}"
    _jobs[job_id] = {'status': 'queued'}

    thread = threading.Thread(
        target=_run_fashn_job,
        args=(job_id, fashn_api_key, model_b64, garment_b64),
        daemon=True
    )
    thread.start()

    return JsonResponse({'ok': True, 'job_id': job_id})


def try_on_status(request, job_id):
    """Poll endpoint — frontend calls this to check job progress."""
    job = _jobs.get(job_id)
    if not job:
        return JsonResponse({'error': 'Job not found'}, status=404)
    return JsonResponse(job)
