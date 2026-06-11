from django.contrib import admin
from django.utils.html import format_html
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'price', 'garment_preview', 'is_active', 'created_at')
    list_filter = ('is_active', 'category', 'brand')
    search_fields = ('name', 'description', 'category', 'brand')
    list_editable = ('is_active',)
    readonly_fields = ('garment_preview_large', 'created_at', 'updated_at')
    fieldsets = (
        ('Product Info', {
            'fields': ('name', 'description', 'price', 'category', 'brand', 'is_active')
        }),
        ('Garment Image (for AI Try-On)', {
            'fields': ('garment_image', 'garment_preview_large'),
            'description': 'Upload a clear product image. This will be used by the AI try-on feature.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def garment_preview(self, obj):
        if obj.garment_image:
            return format_html('<img src="{}" width="60" height="60" style="object-fit:cover;border-radius:6px;"/>', obj.garment_image.url)
        return '—'
    garment_preview.short_description = 'Image'

    def garment_preview_large(self, obj):
        if obj.garment_image:
            return format_html(
                '<img src="{}" style="max-width:300px;max-height:300px;object-fit:cover;border-radius:10px;border:1px solid #ddd;"/>',
                obj.garment_image.url
            )
        return 'No image uploaded yet.'
    garment_preview_large.short_description = 'Current Image Preview'
