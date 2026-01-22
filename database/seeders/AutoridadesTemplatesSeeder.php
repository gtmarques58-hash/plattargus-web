<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;
use App\Models\Autoridade;
use App\Models\TemplateDocumento;
use Illuminate\Support\Facades\DB;

class AutoridadesTemplatesSeeder extends Seeder
{
    /**
     * Importa autoridades do SQLite e templates dos arquivos
     */
    public function run(): void
    {
        $this->importarAutoridades();
        $this->importarTemplates();
    }
    
    /**
     * Importa autoridades do banco SQLite do Telegram
     */
    private function importarAutoridades(): void
    {
        $sqlitePath = '/root/secretario-sei/data/argus_autoridades.db';
        
        if (!file_exists($sqlitePath)) {
            $this->command->warn("Arquivo SQLite não encontrado: {$sqlitePath}");
            $this->command->info("Criando autoridades de exemplo...");
            $this->criarAutoridadesExemplo();
            return;
        }
        
        try {
            $sqlite = new \PDO("sqlite:{$sqlitePath}");
            $stmt = $sqlite->query("SELECT * FROM autoridades WHERE ativo = 1");
            $autoridades = $stmt->fetchAll(\PDO::FETCH_ASSOC);
            
            foreach ($autoridades as $a) {
                Autoridade::updateOrCreate(
                    ['sigla' => $a['chave_busca']],
                    [
                        'nome' => $a['nome_atual'],
                        'posto_grad' => $a['posto_grad'],
                        'cargo' => $a['observacoes'] ?? null,
                        'unidade' => $a['unidade_destino'],
                        'sigla_sei' => $a['sigla_unidade'],
                        'matricula' => $a['matricula'],
                        'portaria' => $a['portaria_nomeacao'] ?? null,
                        'email' => $a['email'],
                        'telefone' => $a['telefone'],
                        'sigla_pai' => $a['sigla_pai'] ?? null,
                        'ativo' => true,
                    ]
                );
            }
            
            $this->command->info("✅ " . count($autoridades) . " autoridades importadas do SQLite");
            
        } catch (\Exception $e) {
            $this->command->error("Erro ao importar autoridades: " . $e->getMessage());
            $this->criarAutoridadesExemplo();
        }
    }
    
    /**
     * Cria autoridades de exemplo caso não tenha o SQLite
     */
    private function criarAutoridadesExemplo(): void
    {
        $autoridades = [
            ['sigla' => 'CMDGER', 'nome' => 'Charles da Silva Santos', 'posto_grad' => 'CEL QOBMEC', 'cargo' => 'Comandante-Geral', 'unidade' => 'Comando Geral do CBMAC'],
            ['sigla' => 'SUBCMD', 'nome' => 'Éden da Silva Santos', 'posto_grad' => 'CEL QOBMEC', 'cargo' => 'Subcomandante-Geral', 'unidade' => 'Subcomando Geral do CBMAC'],
            ['sigla' => 'DRH', 'nome' => 'Gilmar Torres Marques Moura', 'posto_grad' => 'MAJ QOBMEC', 'cargo' => 'Diretor de Recursos Humanos', 'unidade' => 'Diretoria de Recursos Humanos'],
            ['sigla' => 'COI', 'nome' => 'Dyego Ribeiro da Silva Vieira', 'posto_grad' => 'MAJ QOBMEC', 'cargo' => 'Comandante Operacional do Interior', 'unidade' => 'Comando Operacional do Interior'],
            ['sigla' => 'COC', 'nome' => 'Francisco Carlos Santos de Freitas Filho', 'posto_grad' => 'MAJ QOBMEC', 'cargo' => 'Comandante Operacional da Capital', 'unidade' => 'Comando Operacional da Capital'],
        ];
        
        foreach ($autoridades as $a) {
            Autoridade::updateOrCreate(
                ['sigla' => $a['sigla']],
                array_merge($a, ['ativo' => true])
            );
        }
        
        $this->command->info("✅ " . count($autoridades) . " autoridades de exemplo criadas");
    }
    
    /**
     * Importa templates dos arquivos TXT
     */
    private function importarTemplates(): void
    {
        $templates = [
            // DESPACHOS
            [
                'codigo' => 'DESPACHO_SIMPLES',
                'tipo_sei' => 'Despacho',
                'categoria' => 'despachos',
                'nome' => 'Despacho Simples',
                'descricao' => 'Despacho com texto livre para qualquer finalidade',
                'campos' => ['CARGO_DESTINO', 'SIGLA_UNIDADE', 'VOCATIVO', 'TEXTO_CORPO', 'NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 1,
            ],
            [
                'codigo' => 'DESPACHO_ENCAMINHAMENTO',
                'tipo_sei' => 'Despacho',
                'categoria' => 'despachos',
                'nome' => 'Despacho de Encaminhamento',
                'descricao' => 'Despacho para encaminhar processo a outra unidade',
                'campos' => ['CARGO_DESTINO', 'SIGLA_UNIDADE', 'VOCATIVO', 'NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 2,
            ],
            [
                'codigo' => 'DESPACHO_DEFERIMENTO',
                'tipo_sei' => 'Despacho',
                'categoria' => 'despachos',
                'nome' => 'Despacho de Deferimento',
                'descricao' => 'Despacho para deferir solicitação',
                'campos' => ['NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 3,
            ],
            [
                'codigo' => 'DESPACHO_INDEFERIMENTO',
                'tipo_sei' => 'Despacho',
                'categoria' => 'despachos',
                'nome' => 'Despacho de Indeferimento',
                'descricao' => 'Despacho para indeferir solicitação',
                'campos' => ['MOTIVOS_INDEFERIMENTO', 'NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 4,
            ],
            
            // MEMORANDOS
            [
                'codigo' => 'MEMO_GENERICO',
                'tipo_sei' => 'Memorando',
                'categoria' => 'memorandos',
                'nome' => 'Memorando Genérico',
                'descricao' => 'Memorando para qualquer finalidade',
                'campos' => ['NOME_COMPLETO', 'CARGO_DESTINO', 'SIGLA_UNIDADE', 'ASSUNTO_RESUMIDO', 'VOCATIVO', 'TEXTO_CORPO', 'NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'chefe_unidade',
                'ordem' => 1,
            ],
            [
                'codigo' => 'MEMO_ENCAMINHAMENTO',
                'tipo_sei' => 'Memorando',
                'categoria' => 'memorandos',
                'nome' => 'Memorando de Encaminhamento',
                'descricao' => 'Memorando para encaminhar documentos',
                'campos' => ['NOME_COMPLETO', 'CARGO_DESTINO', 'SIGLA_UNIDADE', 'VOCATIVO', 'MOTIVO_ENCAMINHAMENTO', 'NOME_REMETENTE', 'CARGO_REMETENTE', 'SIGLA_REMETENTE'],
                'remetente_tipo' => 'chefe_unidade',
                'ordem' => 2,
            ],
            
            // REQUERIMENTOS
            [
                'codigo' => 'REQ_GENERICO',
                'tipo_sei' => 'Requerimento',
                'categoria' => 'requerimentos',
                'nome' => 'Requerimento Genérico',
                'descricao' => 'Requerimento para qualquer solicitação',
                'campos' => ['NOME_COMANDANTE', 'CARGO_COMANDANTE', 'ASSUNTO', 'NOME_REQUERENTE', 'POSTO_GRAD_REQUERENTE', 'MATRICULA', 'UNIDADE_LOTACAO', 'TEXTO_SOLICITACAO'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 1,
            ],
            [
                'codigo' => 'REQ_FERIAS',
                'tipo_sei' => 'Requerimento',
                'categoria' => 'requerimentos',
                'nome' => 'Requerimento de Férias',
                'descricao' => 'Requerimento para solicitar férias',
                'campos' => ['NOME_COMANDANTE', 'CARGO_COMANDANTE', 'NOME_REQUERENTE', 'POSTO_GRAD_REQUERENTE', 'MATRICULA', 'UNIDADE_LOTACAO', 'PERIODO_FERIAS', 'DATA_INICIO', 'DATA_FIM'],
                'remetente_tipo' => 'usuario_logado',
                'ordem' => 2,
            ],
            
            // OFÍCIOS
            [
                'codigo' => 'OFICIO_EXTERNO',
                'tipo_sei' => 'Ofício',
                'categoria' => 'oficios',
                'nome' => 'Ofício Externo',
                'descricao' => 'Ofício para órgãos externos',
                'campos' => ['NOME_DESTINATARIO', 'CARGO_DESTINATARIO', 'ORGAO_DESTINATARIO', 'ASSUNTO', 'VOCATIVO', 'TEXTO_CORPO', 'NOME_REMETENTE', 'CARGO_REMETENTE'],
                'remetente_tipo' => 'chefe_unidade',
                'ordem' => 1,
            ],
            
            // NOTAS BG
            [
                'codigo' => 'NOTA_BG_VIAGEM',
                'tipo_sei' => 'Nota para Boletim Geral - BG - CBMAC',
                'categoria' => 'notas',
                'nome' => 'Nota BG - Viagem',
                'descricao' => 'Nota para Boletim Geral sobre viagem a serviço',
                'campos' => ['TIPO_ONUS', 'DATA_VIAGEM', 'HORA_SAIDA', 'POSTO_GRAD', 'MATRICULA', 'NOME_MILITAR', 'CIDADE_DESTINO', 'UF_DESTINO', 'MOTIVO_VIAGEM', 'DATA_RETORNO', 'HORA_RETORNO', 'NUP_PROCESSO'],
                'remetente_tipo' => 'chefe_unidade',
                'ordem' => 1,
            ],
        ];
        
        // Carrega conteúdo dos arquivos de template
        $basePath = '/opt/plattargus/modelos';
        
        foreach ($templates as $t) {
            $arquivo = "{$basePath}/{$t['categoria']}/{$t['codigo']}.txt";
            
            if (file_exists($arquivo)) {
                $conteudo = file_get_contents($arquivo);
            } else {
                // Template padrão se arquivo não existir
                $conteudo = $this->getTemplateDefault($t['codigo']);
            }
            
            TemplateDocumento::updateOrCreate(
                ['codigo' => $t['codigo']],
                [
                    'tipo_sei' => $t['tipo_sei'],
                    'categoria' => $t['categoria'],
                    'nome' => $t['nome'],
                    'descricao' => $t['descricao'],
                    'conteudo_html' => $conteudo,
                    'campos' => $t['campos'],
                    'remetente_tipo' => $t['remetente_tipo'],
                    'ordem' => $t['ordem'],
                    'ativo' => true,
                ]
            );
        }
        
        $this->command->info("✅ " . count($templates) . " templates importados");
    }
    
    /**
     * Retorna template padrão para cada tipo
     */
    private function getTemplateDefault(string $codigo): string
    {
        $templates = [
            'DESPACHO_SIMPLES' => '<p style="text-align: left;">Ao(à) Sr(a). <b>{CARGO_DESTINO}</b><br>{SIGLA_UNIDADE}</p>
<p style="text-align: left; text-indent: 1.5cm;">{VOCATIVO}</p>
{TEXTO_CORPO}
<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'DESPACHO_ENCAMINHAMENTO' => '<p style="text-align: left;">Ao(à) Sr(a). <b>{CARGO_DESTINO}</b><br>{SIGLA_UNIDADE}</p>
<p style="text-align: left; text-indent: 1.5cm;">{VOCATIVO}</p>
<p style="text-align: justify; text-indent: 1.5cm;">Encaminho o presente processo para conhecimento e providências cabíveis.</p>
<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'DESPACHO_DEFERIMENTO' => '<p style="text-align: justify; text-indent: 1.5cm;"><b>DEFIRO</b> o pedido constante nos autos, nos termos da legislação vigente.</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'DESPACHO_INDEFERIMENTO' => '<p style="text-align: justify; text-indent: 1.5cm;"><b>INDEFIRO</b> o pedido constante nos autos, pelos seguintes motivos:</p>
<p style="text-align: justify; text-indent: 1.5cm;">{MOTIVOS_INDEFERIMENTO}</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'MEMO_GENERICO' => '<p style="text-align: left;">Ao(à) Sr(a). <b>{NOME_COMPLETO}</b><br>{CARGO_DESTINO} - {SIGLA_UNIDADE}</p>
<p style="text-align: left;">Assunto: <b>{ASSUNTO_RESUMIDO}</b></p>
<p style="text-align: left; text-indent: 1.5cm;">{VOCATIVO}</p>
{TEXTO_CORPO}
<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'MEMO_ENCAMINHAMENTO' => '<p style="text-align: left;">Ao(à) Sr(a). <b>{NOME_COMPLETO}</b><br>{CARGO_DESTINO} - {SIGLA_UNIDADE}</p>
<p style="text-align: left; text-indent: 1.5cm;">{VOCATIVO}</p>
<p style="text-align: justify; text-indent: 1.5cm;">Encaminho, para conhecimento e providências, {MOTIVO_ENCAMINHAMENTO}.</p>
<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>{SIGLA_REMETENTE}/CBMAC</p>',

            'REQ_GENERICO' => '<p style="text-align: left;">Ao Senhor<br><b>{NOME_COMANDANTE}</b><br>{CARGO_COMANDANTE}</p>
<p style="text-align: left;">Assunto: <b>{ASSUNTO}</b></p>
<p style="text-align: left; text-indent: 1.5cm;">Senhor Comandante,</p>
<p style="text-align: justify; text-indent: 1.5cm;">Eu, {NOME_REQUERENTE}, {POSTO_GRAD_REQUERENTE}, matrícula nº {MATRICULA}, lotado(a) no(a) {UNIDADE_LOTACAO}, venho, respeitosamente, à presença de Vossa Senhoria {TEXTO_SOLICITACAO}.</p>
<p style="text-align: justify;">Nestes termos, Pede deferimento.</p>
<p style="text-align: center;"><b>{NOME_REQUERENTE}</b><br>{POSTO_GRAD_REQUERENTE}<br>Matrícula nº {MATRICULA}</p>',

            'REQ_FERIAS' => '<p style="text-align: left;">Ao Senhor<br><b>{NOME_COMANDANTE}</b><br>{CARGO_COMANDANTE}</p>
<p style="text-align: left;">Assunto: <b>Requerimento de Férias</b></p>
<p style="text-align: left; text-indent: 1.5cm;">Senhor Comandante,</p>
<p style="text-align: justify; text-indent: 1.5cm;">Eu, {NOME_REQUERENTE}, {POSTO_GRAD_REQUERENTE}, matrícula nº {MATRICULA}, lotado(a) no(a) {UNIDADE_LOTACAO}, venho, respeitosamente, requerer a concessão de férias referente ao período aquisitivo {PERIODO_FERIAS}, a serem gozadas de {DATA_INICIO} a {DATA_FIM}.</p>
<p style="text-align: justify;">Nestes termos, Pede deferimento.</p>
<p style="text-align: center;"><b>{NOME_REQUERENTE}</b><br>{POSTO_GRAD_REQUERENTE}<br>Matrícula nº {MATRICULA}</p>',

            'OFICIO_EXTERNO' => '<p style="text-align: left;">Ao Senhor(a)<br><b>{NOME_DESTINATARIO}</b><br>{CARGO_DESTINATARIO}<br>{ORGAO_DESTINATARIO}</p>
<p style="text-align: left;">Assunto: <b>{ASSUNTO}</b></p>
<p style="text-align: left; text-indent: 1.5cm;">{VOCATIVO}</p>
{TEXTO_CORPO}
<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>
<p style="text-align: center;"><b>{NOME_REMETENTE}</b><br>{CARGO_REMETENTE}<br>Corpo de Bombeiros Militar do Estado do Acre</p>',

            'NOTA_BG_VIAGEM' => '<p style="text-align: justify;"><b>VIAGEM A SERVIÇO</b></p>
<p style="text-align: justify;">Tipo de Ônus: {TIPO_ONUS}</p>
<p style="text-align: justify;">O(A) {POSTO_GRAD} {NOME_MILITAR}, matrícula {MATRICULA}, viajará no dia {DATA_VIAGEM}, às {HORA_SAIDA}, com destino a {CIDADE_DESTINO}/{UF_DESTINO}, a fim de {MOTIVO_VIAGEM}, com previsão de retorno em {DATA_RETORNO}, às {HORA_RETORNO}.</p>
<p style="text-align: justify;">Processo SEI nº {NUP_PROCESSO}</p>',
        ];
        
        return $templates[$codigo] ?? '<p>{TEXTO_CORPO}</p>';
    }
}
