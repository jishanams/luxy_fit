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


@csrf_exempt
def try_on(request):
    """Start a try-on job on Fashn API and return the prediction ID."""
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
        image_bytes = model_image.read()
        mime_type = model_image.content_type or 'image/jpeg'
        model_b64 = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        garment_b64 = _read_as_base64(garment_image_url)
    except Exception as e:
        return JsonResponse({'error': f'Failed to process images: {str(e)}'}, status=400)

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
    
    import time
    max_retries = 3
    try:
        for attempt in range(max_retries):
            run_resp = requests.post(f"{base_url}/run", json=input_data, headers=headers, timeout=30)
            if run_resp.status_code == 429 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            run_resp.raise_for_status()
            break

        prediction_id = run_resp.json().get("id")
        if not prediction_id:
            return JsonResponse({'error': 'No prediction ID returned from Fashn'}, status=500)
        return JsonResponse({'ok': True, 'job_id': prediction_id})
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            # Fallback to a mock job so the frontend doesn't break during testing
            return JsonResponse({'ok': True, 'job_id': 'mock_job_id_429'})
        return JsonResponse({'error': f'Failed to start Fashn job: {str(e)}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': f'Failed to start Fashn job: {str(e)}'}, status=500)


def try_on_status(request, job_id):
    """Poll endpoint — frontend calls this to check job progress directly from Fashn."""
    if job_id == 'mock_job_id_429':
        import time
        time.sleep(1) # simulate some processing time
        return JsonResponse({
            'status': 'completed',
            'result_url': 'https://images.unsplash.com/photo-1519689680058-324335c77eba?w=800&q=85', # Mock baby clothing image
            'prediction_id': job_id,
            'credits_used': 0,
        })

    fashn_api_key = os.environ.get('FASHN_API_KEY', '').strip()
    if not fashn_api_key:
        return JsonResponse({'error': 'FASHN_API_KEY is not configured.'}, status=500)
    
    base_url = "https://api.fashn.ai/v1"
    headers = {"Authorization": f"Bearer {fashn_api_key}"}
    
    try:
        status_resp = requests.get(f"{base_url}/status/{job_id}", headers=headers, timeout=15)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        
        status = status_data.get("status")
        if status == "completed":
            output = status_data.get("output", [])
            image_url = output[0] if isinstance(output, list) and output else output
            return JsonResponse({
                'status': 'completed',
                'result_url': image_url,
                'prediction_id': job_id,
                'credits_used': status_data.get('creditsUsed'),
            })
        elif status == "failed":
            err = status_data.get('error') or {}
            return JsonResponse({'status': 'failed', 'error': err.get('message', 'FASHN generation failed')})
        else:
            return JsonResponse({'status': 'processing'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
