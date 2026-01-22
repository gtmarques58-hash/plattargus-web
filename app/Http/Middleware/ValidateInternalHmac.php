<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * ValidateInternalHmac - Valida assinatura HMAC para rotas internas
 * 
 * Usado para comunicação segura entre Engine (FastAPI) e Laravel.
 */
class ValidateInternalHmac
{
    /**
     * Janela de tempo permitida (segundos).
     * Previne replay attacks.
     */
    private const TIME_WINDOW = 300; // 5 minutos

    /**
     * Handle an incoming request.
     */
    public function handle(Request $request, Closure $next): Response
    {
        $secret = config('services.platt_engine.secret');
        
        if (empty($secret)) {
            \Log::error('HMAC validation failed: PLATT_ENGINE_SECRET not configured');
            return response()->json(['error' => 'Internal configuration error'], 500);
        }

        // Headers obrigatórios
        $timestamp = $request->header('X-Timestamp');
        $signature = $request->header('X-Signature');
        $requestId = $request->header('X-Request-ID');

        if (!$timestamp || !$signature) {
            return response()->json(['error' => 'Missing authentication headers'], 401);
        }

        // Valida timestamp (anti-replay)
        $now = time();
        $requestTime = (int) $timestamp;
        
        if (abs($now - $requestTime) > self::TIME_WINDOW) {
            \Log::warning('HMAC validation failed: timestamp out of window', [
                'now' => $now,
                'request_time' => $requestTime,
                'diff' => abs($now - $requestTime),
            ]);
            return response()->json(['error' => 'Request expired'], 401);
        }

        // Reconstrói assinatura
        $method = strtoupper($request->method());
        $path = '/' . ltrim($request->path(), '/');
        $body = $request->getContent();
        $bodyHash = hash('sha256', $body);
        
        $base = $timestamp . "\n" . $method . "\n" . $path . "\n" . $bodyHash;
        $expectedSignature = hash_hmac('sha256', $base, $secret);

        // Comparação segura (timing-safe)
        if (!hash_equals($expectedSignature, $signature)) {
            \Log::warning('HMAC validation failed: signature mismatch', [
                'path' => $path,
                'request_id' => $requestId,
            ]);
            return response()->json(['error' => 'Invalid signature'], 401);
        }

        // Adiciona request_id ao contexto
        if ($requestId) {
            \Log::withContext(['request_id' => $requestId]);
        }

        return $next($request);
    }
}
