<?php

use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Schedule;

/*
|--------------------------------------------------------------------------
| Console Routes
|--------------------------------------------------------------------------
*/

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

/*
|--------------------------------------------------------------------------
| Scheduled Tasks
|--------------------------------------------------------------------------
*/

// Limpa sessões expiradas do SEI (diariamente às 3h)
Schedule::command('model:prune', ['--model' => 'App\\Models\\SeiSession'])
    ->dailyAt('03:00')
    ->timezone('America/Rio_Branco');

// Limpa jobs antigos (semanalmente)
Schedule::command('queue:prune-batches --hours=168')
    ->weekly()
    ->timezone('America/Rio_Branco');

// Limpa tokens Sanctum expirados (diariamente)
Schedule::command('sanctum:prune-expired --hours=24')
    ->daily()
    ->timezone('America/Rio_Branco');
