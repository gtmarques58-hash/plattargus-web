<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class GeneratedDocument extends Model
{
    protected $fillable = [
        'user_id',
        'process_analysis_id',
        'nup',
        'tipo',
        'destinatario',
        'conteudo_html',
        'conteudo_texto',
        'sei_numero',
        'inserido_sei',
        'assinado',
        'inserido_em',
        'assinado_em',
    ];

    protected $casts = [
        'inserido_sei' => 'boolean',
        'assinado' => 'boolean',
        'inserido_em' => 'datetime',
        'assinado_em' => 'datetime',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function processAnalysis(): BelongsTo
    {
        return $this->belongsTo(ProcessAnalysis::class);
    }
}
