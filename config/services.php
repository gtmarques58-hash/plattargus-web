<?php

return [

    /*
    |--------------------------------------------------------------------------
    | Third Party Services
    |--------------------------------------------------------------------------
    */

    'mailgun' => [
        'domain' => env('MAILGUN_DOMAIN'),
        'secret' => env('MAILGUN_SECRET'),
        'endpoint' => env('MAILGUN_ENDPOINT', 'api.mailgun.net'),
        'scheme' => 'https',
    ],

    'postmark' => [
        'token' => env('POSTMARK_TOKEN'),
    ],

    'ses' => [
        'key' => env('AWS_ACCESS_KEY_ID'),
        'secret' => env('AWS_SECRET_ACCESS_KEY'),
        'region' => env('AWS_DEFAULT_REGION', 'us-east-1'),
    ],

    'slack' => [
        'notifications' => [
            'bot_user_oauth_token' => env('SLACK_BOT_USER_OAUTH_TOKEN'),
            'channel' => env('SLACK_BOT_USER_DEFAULT_CHANNEL'),
        ],
    ],

    /*
    |--------------------------------------------------------------------------
    | PlattArgus - Configurações de Segurança
    |--------------------------------------------------------------------------
    */

    'argus' => [
        // Master Key para criptografia AES-256-GCM
        // NUNCA exponha esta chave! Mantenha apenas no .env
        'master_key' => env('ARGUS_MASTER_KEY'),
    ],

    /*
    |--------------------------------------------------------------------------
    // PlattArgus - Engine FastAPI
    |--------------------------------------------------------------------------
    */

    'platt_engine' => [
        // URL do Engine (FastAPI)
        'url' => env('PLATT_ENGINE_URL', 'http://localhost:8000'),

        // URL do Runner (Playwright scripts)
        'runner_url' => env('PLATT_RUNNER_URL', 'http://localhost:8001'),

        // Secret para HMAC (comunicação interna)
        'secret' => env('PLATT_ENGINE_SECRET'),

        // Timeout para requisições (segundos)
        'timeout' => env('PLATT_ENGINE_TIMEOUT', 120),
    ],

    /*
    |--------------------------------------------------------------------------
    // PlattArgus - Step-Up Authentication
    |--------------------------------------------------------------------------
    */

    'step_up' => [
        // Tempo de validade do grant (segundos)
        'ttl' => env('STEP_UP_TTL', 90),
        
        // Máximo de tentativas antes de bloquear
        'max_attempts' => env('STEP_UP_MAX_ATTEMPTS', 5),
        
        // Tempo de bloqueio (minutos)
        'lockout_minutes' => env('STEP_UP_LOCKOUT_MINUTES', 15),
    ],

];
