async function probarOperacionesPersistentes(fuente) {
    const memoria = new Map(), llamadas = [], respuestas = [];
    const eventos = {};
    let comprobaciones = 0;
    function verificar(valor, mensaje) {if (!valor) throw new Error(mensaje); comprobaciones++;}
    class Formulario {
        constructor() {this.datos = new Map();}
        set(k,v) {this.datos.set(k,v);}
        [Symbol.iterator]() {return this.datos.entries();}
    }
    class Direccion {
        constructor(valor) {this.origin = 'https://local.test'; this.pathname = valor.replace('https://local.test','');}
    }
    function iniciar() {
        const nodos = [];
        function crear(tipo) {const nodo = {tipo, hijos: [], append(...n) {this.hijos.push(...n);},
            appendChild(n) {this.hijos.push(n);}, setAttribute() {}, addEventListener() {},
            querySelector(tipo) {return this.hijos.find(n => n.tipo === tipo);}, remove() {this.id = '';}};
            nodos.push(nodo); return nodo;}
        const document = {querySelector() {return {content:'mesero'};}, createElement: crear,
            getElementById(id) {return nodos.find(n => n.id === id);}, body: crear('body'),
            addEventListener(tipo, fn) {eventos[tipo] = fn;}};
        const window = {location: {href:'https://local.test/',origin:'https://local.test'},
            addEventListener(tipo, fn) {eventos[tipo] = fn;}, dispatchEvent() {}};
        const storage = {getItem:k=>memoria.get(k)||null,setItem:(k,v)=>memoria.set(k,v),removeItem:k=>memoria.delete(k)};
        let secuencia = 0;
        const fetch = async (url, opciones) => {
            llamadas.push({url, opciones});
            const respuesta = respuestas.shift();
            if (respuesta instanceof Error) throw respuesta;
            return {...respuesta, json: async()=>respuesta.datos};
        };
        new Function('window','document','localStorage','fetch','crypto','FormData','URL','AbortController','CustomEvent','setTimeout','clearTimeout','alert',fuente)(
            window,document,storage,fetch,{getRandomValues(b) {b.fill(++secuencia);return b;}},Formulario,Direccion,
            class {constructor(){this.signal={};} abort(){}},class{},()=>1,()=>{},()=>{});
        return window;
    }
    let app = iniciar();
    const datos = {pedido_id:1};
    respuestas.push(new Error('Se perdió la respuesta después de guardar'));
    try {await app.operarPedido('/guardar_historico',datos);} catch(error) {}
    verificar(memoria.size===1,'Se descartó una operación con resultado desconocido');
    const primeraClave=llamadas[0].opciones.headers['Idempotency-Key'];
    try {await app.operarPedido('/guardar_historico',{pedido_id:2});} catch(error) {}
    verificar(llamadas.length===1,'Se permitió otra operación sin resolver la anterior');
    app=iniciar();
    respuestas.push({ok:true,status:200,datos:{success:true}});
    await eventos.DOMContentLoaded();
    verificar(llamadas[1].opciones.headers['Idempotency-Key']===primeraClave,'La recarga cambió la clave del reintento');
    verificar(memoria.size===0,'No se retiró una operación confirmada');
    respuestas.push({ok:false,status:400,datos:{codigo:'SESION_RECARGAR',message:'Recarga'}});
    try {await app.operarPedido('/guardar_historico',{pedido_id:3});} catch(error) {}
    verificar(memoria.size===1,'Un token vencido perdió el estado incierto de la operación');
    respuestas.push({ok:true,status:200,datos:{success:true}});
    await eventos.online();
    verificar(memoria.size===0,'No se confirmó la operación al reconectar');
    const form=new Formulario();form.set('producto_id','1');form.set('cantidad','2');form.set('csrf_token','antiguo');
    respuestas.push({ok:false,status:409,datos:{success:false,codigo:'PRECIO_CAMBIO',message:'Precio cambiado'}});
    let rechazo=false;
    try {await app.operarPedido('/agregar_producto_pedido/1',form);} catch(error) {rechazo=error.datos.codigo==='PRECIO_CAMBIO';}
    verificar(rechazo && memoria.size===0,'No se liberó una validación de precio rechazada');
    verificar(!JSON.parse(llamadas[2].opciones.body).csrf_token,'Se guardó un token de sesión en el cuerpo JSON');
    return comprobaciones;
}

async function probarAvisosReconexion(fuente) {
    const memoria=new Map([['marisqueria:tickets-vistos:cajero','[1]']]);
    const callbacks={},nodos=new Map();
    const pendientes=[1,2];
    function nodo(id) {
        if(!nodos.has(id)) nodos.set(id,{hidden:true,textContent:'',innerHTML:'',
            addEventListener(){},getAnimations(){return[];},querySelectorAll(){return[];}});
        return nodos.get(id);
    }
    const document={hidden:false,getElementById:nodo,querySelector(){return{content:'cajero'};},
        querySelectorAll(){return[{dataset:{avisoId:'1'}}];},addEventListener(){}};
    const window={location:{},addEventListener(){},scrollY:0,scrollX:0,scrollTo(){}};
    const nuevo={innerHTML:'tickets',querySelectorAll(selector){
        return selector==='[data-aviso-id]'?pendientes.map(id=>({dataset:{avisoId:String(id),avisoFolio:'T-'+id,avisoUsuario:'mesero'}})):[];
    }};
    const storage={getItem:k=>memoria.get(k)||null,setItem:(k,v)=>memoria.set(k,v),removeItem:k=>memoria.delete(k)};
    new Function('window','document','sessionStorage','io','fetch','DOMParser','setTimeout','clearTimeout','alert',fuente)(
        window,document,storage,()=>({on(k,fn){callbacks[k]=fn;}}),
        async()=>({ok:true,redirected:false,text:async()=>''}),
        class{parseFromString(){return{getElementById(){return nuevo;}};}},()=>1,()=>{},()=>{});
    await callbacks.connect();
    if(!nodo('avisoTicketCajaDetalle').textContent.includes('T-2')) throw new Error('No avisó del ticket perdido durante el corte');
    nodo('avisoTicketCaja').hidden=true;
    await callbacks.connect();
    if(!nodo('avisoTicketCaja').hidden) throw new Error('Volvió a notificar un ticket conocido');
    pendientes.push(3);
    await callbacks.connect();
    if(!nodo('avisoTicketCajaDetalle').textContent.includes('T-3')) throw new Error('No recuperó la segunda desconexión');
    return 3;
}
