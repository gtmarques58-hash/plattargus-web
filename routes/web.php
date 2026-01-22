<?php

use Illuminate\Support\Facades\Route;

/*
|--------------------------------------------------------------------------
| Web Routes
|--------------------------------------------------------------------------
|
| Rotas web do PlattArgus
| O frontend principal é servido como SPA (Single Page Application)
|
*/

// Health check
Route::get('/up', function () {
    return response()->json(['status' => 'ok']);
});

// SPA catch-all (redireciona para o frontend)
Route::get('/{any}', function () {
    return file_get_contents(public_path('index.html'));
})->where('any', '^(?!api).*$');
