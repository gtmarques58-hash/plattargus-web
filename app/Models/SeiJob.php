<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SeiJob extends Model
{
    protected $table = 'sei_jobs';
    
    public $incrementing = false;
    protected $keyType = 'string';

    protected $fillable = [
        'id',
        'user_id',
        'type',
        'status',
        'nup',
        'sei_numero',
        'request_data',
        'result_data',
        'error_message',
        'progress_pct',
        'progress_step',
        'started_at',
        'finished_at',
    ];

    protected $casts = [
        'request_data' => 'array',
        'result_data' => 'array',
        'started_at' => 'datetime',
        'finished_at' => 'datetime',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    // Status helpers
    public function isQueued(): bool
    {
        return $this->status === 'queued';
    }

    public function isRunning(): bool
    {
        return $this->status === 'running';
    }

    public function isDone(): bool
    {
        return $this->status === 'done';
    }

    public function hasError(): bool
    {
        return $this->status === 'error';
    }
}
