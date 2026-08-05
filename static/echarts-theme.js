// echarts-theme.js —— ECharts「终端」暗色主题，配合 style.css 的黑底终端风
// 用法：先引入 echarts.min.js，再引入本文件，然后 echarts.init(el, 'terminal')
(function () {
    const C = {
        fg: '#D7D7D7', dim: '#8A8A8A', line: '#292929', strong: '#3A3A3A',
        amber: '#F28C00', up: '#FF4D4F', down: '#00C176', cyan: '#4DD0E1', panel: '#0A0A0A'
    };
    const axis = {
        axisLine: { lineStyle: { color: C.strong } },
        axisTick: { lineStyle: { color: C.strong } },
        axisLabel: { color: C.dim },
        splitLine: { lineStyle: { color: C.line } }
    };
    echarts.registerTheme('terminal', {
        // 折线配色：琥珀打头，红绿涨跌，再补几支终端风亮色
        color: [C.amber, C.cyan, C.up, C.down, '#B37FEB', '#5A8CFF', '#FFD666', '#FF7A45'],
        backgroundColor: 'transparent',
        textStyle: {
            color: C.fg,
            fontFamily: "'IBM Plex Mono', Menlo, Consolas, 'PingFang SC', 'Microsoft YaHei', monospace"
        },
        legend: { textStyle: { color: C.dim } },
        tooltip: {
            backgroundColor: C.panel, borderColor: C.strong, borderWidth: 1,
            textStyle: { color: C.fg, fontSize: 12 }
        },
        categoryAxis: axis,
        valueAxis: axis,
        timeAxis: axis,
        dataZoom: {
            backgroundColor: 'rgba(0,0,0,0)',
            dataBackground: {
                lineStyle: { color: C.strong },
                areaStyle: { color: C.line, opacity: 0.6 }
            },
            selectedDataBackground: {
                lineStyle: { color: C.amber },
                areaStyle: { color: C.amber, opacity: 0.2 }
            },
            fillerColor: 'rgba(242,140,0,0.12)',
            handleColor: C.amber,
            moveHandleColor: C.amber,
            emphasis: { moveHandleColor: C.amber },
            textStyle: { color: C.dim },
            borderColor: C.strong
        }
    });
})();
