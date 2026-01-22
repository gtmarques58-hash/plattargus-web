<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class ProcessAnalysis extends Model
{
    protected $table = 'process_analyses';

    protected $fillable = [
        'job_id',
        'user_id',
        'nup',
        'resumo',
        'conclusao',
        'interessado',
        'pedido',
        'legislacao',
        'documentos',
        'alertas',
        'unidades',
        'texto_canonico',
    ];

    protected $casts = [
        'interessado' => 'array',
        'pedido' => 'array',
        'legislacao' => 'array',
        'documentos' => 'array',
        'alertas' => 'array',
        'unidades' => 'array',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function generatedDocuments(): HasMany
    {
        return $this->hasMany(GeneratedDocument::class);
    }
}
