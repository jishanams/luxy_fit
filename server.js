import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import Fashn from 'fashn';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;
const PUBLIC_BASE_URL = (process.env.PUBLIC_BASE_URL || `http://localhost:${PORT}`).replace(/\/$/, '');
const DEFAULT_GARMENT_IMAGE_URL = process.env.PRODUCT_GARMENT_IMAGE_URL || '';

const uploadDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname || '').toLowerCase() || '.jpg';
    cb(null, `${Date.now()}-${Math.round(Math.random() * 1e9)}${ext}`);
  }
});

const upload = multer({
  storage,
  limits: { fileSize: 10 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    if (!file.mimetype.startsWith('image/')) return cb(new Error('Only image files are allowed'));
    cb(null, true);
  }
});

app.use(cors());
app.use(express.json({ limit: '1mb' }));
app.use('/uploads', express.static(uploadDir));
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, publicBaseUrl: PUBLIC_BASE_URL });
});

app.post('/api/try-on', upload.single('model_image'), async (req, res) => {
  try {
    if (!process.env.FASHN_API_KEY) {
      return res.status(500).json({ error: 'Missing FASHN_API_KEY in .env' });
    }

    if (!req.file) {
      return res.status(400).json({ error: 'model_image file is required' });
    }

    const garmentImage = req.body.garment_image_url || DEFAULT_GARMENT_IMAGE_URL;
    if (!garmentImage) {
      return res.status(400).json({ error: 'garment_image_url is required. Add PRODUCT_GARMENT_IMAGE_URL in .env or send it from frontend.' });
    }

    const modelImageUrl = `${PUBLIC_BASE_URL}/uploads/${req.file.filename}`;

    const client = new Fashn({ apiKey: process.env.FASHN_API_KEY });

    const response = await client.predictions.subscribe({
      model_name: 'tryon-v1.6',
      inputs: {
        model_image: modelImageUrl,
        garment_image: garmentImage,
        category: 'auto'
      }
    });

    if (response.status !== 'completed') {
      return res.status(422).json({
        error: response.error?.message || 'FASHN generation failed',
        status: response.status,
        details: response.error || null
      });
    }

    const output = response.output;
    const imageUrl = Array.isArray(output) ? output[0] : output?.[0] || output?.url || output?.image_url || output;

    res.json({
      ok: true,
      prediction_id: response.id,
      credits_used: response.creditsUsed,
      result_url: imageUrl,
      raw_output: output
    });
  } catch (err) {
    console.error(err);
    res.status(err.status || 500).json({
      error: err.message || 'Server error',
      status: err.status || 500
    });
  }
});

app.listen(PORT, () => {
  console.log(`LuxyTrends AI Try-On running at http://localhost:${PORT}`);
  console.log(`Public base URL: ${PUBLIC_BASE_URL}`);
});
